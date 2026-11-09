// SPDX-License-Identifier: Apache-2.0
//
// Benchmark adapter: makes Autoware's autoware_ndt_scan_matcher align with fast_gicp::NDTCuda.
//
// - The pose comes from fast_gicp::NDTCuda (P2D distance, DIRECT7 neighbor search, Levenberg-Marquardt).
// - fast_gicp computes no transform probability and no NVTL, which Autoware needs to accept a pose. They are computed
//   at the final pose by ndt_cuda's GPU kernels (the base class), with the same voxels as Autoware's NDT.
// - Map tiles: the point clouds of the loaded tiles are merged and given to fast_gicp, which builds its own voxel map
//   on the GPU. Copies (made by Autoware's map update thread) prepare both GPU maps right away, so that this work does
//   not run in the scan callback.
//
// For the comparison benchmark only.

#ifndef AUTOWARE__NDT_SCAN_MATCHER__NDT_OMP__MULTIGRID_NDT_OMP_H_
#define AUTOWARE__NDT_SCAN_MATCHER__NDT_OMP__MULTIGRID_NDT_OMP_H_

#include "ndt_struct.hpp"

#include <fast_gicp/ndt/ndt_cuda.hpp>
#include <ndt_cuda/multigrid_ndt_cuda.hpp>

#include <pcl/common/transforms.h>

#include <map>
#include <memory>
#include <string>

namespace pclomp
{
namespace detail
{
template <typename PointSource, typename PointTarget>
class FastNdt : public fast_gicp::NDTCuda<PointSource, PointTarget>
{
public:
  // fast_gicp stores the index of the last iteration
  int iterations() const { return this->nr_iterations_ + 1; }
};
}  // namespace detail

template <typename PointSource, typename PointTarget>
class MultiGridNormalDistributionsTransform
: public ndt_cuda::MultiGridNormalDistributionsTransformCUDA<PointSource, PointTarget>
{
  using Base = ndt_cuda::MultiGridNormalDistributionsTransformCUDA<PointSource, PointTarget>;
  using FastNdt = detail::FastNdt<PointSource, PointTarget>;
  using SourceCloud = pcl::PointCloud<PointSource>;
  using TargetCloud = pcl::PointCloud<PointTarget>;
  using TargetCloudConstPtr = typename TargetCloud::ConstPtr;

public:
  using Ptr = pcl::shared_ptr<MultiGridNormalDistributionsTransform<PointSource, PointTarget>>;
  using ConstPtr = pcl::shared_ptr<const MultiGridNormalDistributionsTransform<PointSource, PointTarget>>;

  MultiGridNormalDistributionsTransform() { this->setUseAutowareCovariance(true); }

  MultiGridNormalDistributionsTransform(const MultiGridNormalDistributionsTransform & other)
  : Base(other), clouds_(other.clouds_), merged_(other.merged_)
  {
    prepare();
  }

  MultiGridNormalDistributionsTransform & operator=(const MultiGridNormalDistributionsTransform & other)
  {
    if (this != &other) {
      Base::operator=(other);
      clouds_ = other.clouds_;
      merged_ = other.merged_;
      prepare();
    }
    return *this;
  }

  // Autoware asks whether map tiles are loaded.
  bool hasTarget() const { return !this->getCurrentMapIDs().empty(); }

  // Autoware passes the scan to align() instead of calling setInputSource().
  using Base::align;
  void align(SourceCloud & output, const Eigen::Matrix4f & guess, const typename SourceCloud::ConstPtr & source)
  {
    this->setInputSource(source);
    this->align(output, guess);
  }

  void setInputTarget(const TargetCloudConstPtr & cloud) override
  {
    clouds_.clear();
    clouds_["default"] = cloud;
    Base::setInputTarget(cloud);
    merge();
    prepare();
  }

  void addTarget(const TargetCloudConstPtr & cloud, const std::string & target_id)
  {
    Base::addTarget(cloud, target_id);
    clouds_[target_id] = cloud;
  }

  void removeTarget(const std::string & target_id)
  {
    Base::removeTarget(target_id);
    clouds_.erase(target_id);
  }

  void createVoxelKdtree()
  {
    Base::createVoxelKdtree();
    merge();
    prepare();
  }

protected:
  void computeTransformation(SourceCloud & output, const Eigen::Matrix4f & guess) override
  {
    this->nr_iterations_ = 0;
    this->converged_ = false;
    this->transformation_array_.clear();
    this->transform_probability_array_.clear();
    this->nearest_voxel_transformation_likelihood_array_.clear();
    this->hessian_.setZero();

    if (!fast_ || !merged_ || merged_->empty()) {
      this->final_transformation_ = guess;
      this->trans_probability_ = 0.0;
      this->nearest_voxel_transformation_likelihood_ = 0.0;
      this->transformation_array_.push_back(guess);
      this->transform_probability_array_.push_back(0.0f);
      this->nearest_voxel_transformation_likelihood_array_.push_back(0.0f);
      pcl::transformPointCloud(*this->input_, output, guess);
      return;
    }

    this->updateGaussParams();

    fast_->setResolution(this->resolution_);
    fast_->setMaximumIterations(this->max_iterations_);
    fast_->setTransformationEpsilon(this->transformation_epsilon_);
    fast_->setInputSource(this->input_);
    SourceCloud aligned;
    fast_->align(aligned, guess);

    this->final_transformation_ = fast_->getFinalTransformation();
    this->converged_ = fast_->hasConverged();
    this->nr_iterations_ = std::min(fast_->iterations(), this->max_iterations_);

    pcl::transformPointCloud(*this->input_, output, this->final_transformation_);
    this->trans_probability_ = this->calculateTransformationProbability(output);
    this->nearest_voxel_transformation_likelihood_ = this->calculateNearestVoxelTransformationLikelihood(output);

    // fast_gicp does not record the intermediate poses. Autoware expects iteration_num + 1 entries.
    this->transformation_array_.push_back(guess);
    for (int i = 0; i < this->nr_iterations_; i++) {
      this->transformation_array_.push_back(this->final_transformation_);
    }
    this->transform_probability_array_.assign(
      this->nr_iterations_ + 1, static_cast<float>(this->trans_probability_));
    this->nearest_voxel_transformation_likelihood_array_.assign(
      this->nr_iterations_ + 1, static_cast<float>(this->nearest_voxel_transformation_likelihood_));
  }

private:
  void merge()
  {
    auto merged = std::make_shared<TargetCloud>();
    for (const auto & [id, cloud] : clouds_) {
      (void)id;
      *merged += *cloud;
    }
    merged_ = merged;
  }

  /// Uploads both GPU maps now: ndt_cuda's voxels (for the scores) and fast_gicp's voxel map (for the alignment).
  void prepare()
  {
    if (!this->tiles_.empty()) {
      this->prepareTarget();
    }
    fast_ = std::make_shared<FastNdt>();
    fast_->setDistanceMode(fast_gicp::NDTDistanceMode::P2D);
    fast_->setNeighborSearchMethod(fast_gicp::NeighborSearchMethod::DIRECT7);
    fast_->setResolution(this->resolution_);
    if (!merged_ || merged_->empty()) {
      return;
    }
    fast_->setInputTarget(merged_);
    // fast_gicp builds its voxel map in the first align(). One align with a single point builds it here.
    auto one_point = std::make_shared<SourceCloud>();
    PointSource p;
    p.x = merged_->points.front().x;
    p.y = merged_->points.front().y;
    p.z = merged_->points.front().z;
    one_point->push_back(p);
    fast_->setMaximumIterations(1);
    fast_->setInputSource(one_point);
    SourceCloud unused;
    fast_->align(unused, Eigen::Matrix4f::Identity());
  }

  std::map<std::string, TargetCloudConstPtr> clouds_;
  std::shared_ptr<const TargetCloud> merged_;
  std::shared_ptr<FastNdt> fast_;
};
}  // namespace pclomp

#endif  // AUTOWARE__NDT_SCAN_MATCHER__NDT_OMP__MULTIGRID_NDT_OMP_H_
