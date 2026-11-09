// Measures where ndt_cuda's map upload happens when Autoware's MapUpdateModule copies the NDT object.
// Synthetic map: 15 x 15 tiles of 20 m (300 m x 300 m, like map_radius 150 m), resolution 2 m.
#include <ndt_cuda/multigrid_ndt_cuda.hpp>

#include <pcl/point_types.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <random>
#include <string>

using PointT = pcl::PointXYZ;
using Ndt = ndt_cuda::MultiGridNormalDistributionsTransformCUDA<PointT, PointT>;
using Clock = std::chrono::steady_clock;

static double ms(Clock::time_point a, Clock::time_point b) {
  return std::chrono::duration<double, std::milli>(b - a).count();
}

int main() {
  const double ox = 89000.0, oy = 42000.0;  // map coordinates of the size used by Autoware's sample map
  const double tile = 20.0, res = 2.0;
  const int tiles_per_side = 15;
  std::mt19937 rng(1);
  std::uniform_real_distribution<float> u(0.0f, 1.0f);

  Ndt secondary;
  secondary.setResolution(res);
  secondary.setMaximumIterations(30);
  secondary.setTransformationEpsilon(0.01);
  secondary.setStepSize(0.1);

  pcl::PointCloud<PointT>::Ptr source(new pcl::PointCloud<PointT>);
  std::size_t total_points = 0;
  for (int tx = 0; tx < tiles_per_side; tx++) {
    for (int ty = 0; ty < tiles_per_side; ty++) {
      pcl::PointCloud<PointT>::Ptr cloud(new pcl::PointCloud<PointT>);
      // ground plane (slightly bumpy) plus vertical structure in some voxel columns
      for (double x = 0; x < tile; x += res) {
        for (double y = 0; y < tile; y += res) {
          const int layers = (static_cast<int>((tx * tile + x) / res) * 7 + static_cast<int>((ty * tile + y) / res) * 13) % 5 == 0 ? 4 : 1;
          for (int z = 0; z < layers; z++) {
            for (int k = 0; k < 12; k++) {
              PointT p;
              p.x = static_cast<float>(ox + tx * tile + x + res * u(rng));
              p.y = static_cast<float>(oy + ty * tile + y + res * u(rng));
              p.z = static_cast<float>(z * res + (z == 0 ? 0.3f * u(rng) : res * u(rng)));
              cloud->push_back(p);
              const double cx = tx * tile + x - 150.0, cy = ty * tile + y - 150.0;
              if (cx * cx + cy * cy < 60.0 * 60.0 && u(rng) < 0.02f) {
                // scan in the vehicle frame, vehicle at map center
                source->push_back(PointT(p.x - static_cast<float>(ox + 150.0), p.y - static_cast<float>(oy + 150.0), p.z));
              }
            }
          }
        }
      }
      total_points += cloud->size();
      secondary.addTarget(cloud, std::to_string(tx) + "_" + std::to_string(ty));
    }
  }

  auto t0 = Clock::now();
  secondary.createVoxelKdtree();  // map thread in Autoware
  auto t1 = Clock::now();
  std::printf("map points %zu, voxels on GPU %zu, source points %zu\n", total_points, secondary.getNumTargetVoxels(), source->size());
  std::printf("secondary.createVoxelKdtree() (map thread)        : %8.2f ms\n", ms(t0, t1));

  if (getenv("WARM")) {
    pcl::PointCloud<PointT> warm_out;
    Eigen::Matrix4f g = Eigen::Matrix4f::Identity();
    g(0, 3) = static_cast<float>(ox + 150.0 + 0.3);
    g(1, 3) = static_cast<float>(oy + 150.0 - 0.2);
    secondary.setInputSource(source);
    for (int i = 0; i < 3; i++) {
      t0 = Clock::now();
      secondary.align(warm_out, g);
      t1 = Clock::now();
      std::printf("warm-up align #%d on the original                 : %8.2f ms\n", i + 1, ms(t0, t1));
    }
  }
  // Autoware: auto new_ndt_ptr = std::make_shared<NdtType>(*secondary_ndt_ptr); then swap into ndt_ptr_ (map thread)
  t0 = Clock::now();
  auto active = std::make_shared<Ndt>(secondary);
  t1 = Clock::now();
  std::printf("copy constructor (map thread)                     : %8.2f ms\n", ms(t0, t1));

  Eigen::Matrix4f guess = Eigen::Matrix4f::Identity();
  guess(0, 3) = static_cast<float>(ox + 150.0 + 0.3);
  guess(1, 3) = static_cast<float>(oy + 150.0 - 0.2);
  pcl::PointCloud<PointT> out;
  active->setInputSource(source);
  for (int i = 0; i < 5; i++) {
    t0 = Clock::now();
    active->align(out, guess);  // scan callback thread, holds the ndt_ptr_ lock
    t1 = Clock::now();
    std::printf("align #%d on the copy (scan thread)               : %8.2f ms  (iters %d)\n", i + 1, ms(t0, t1), active->getFinalNumIteration());
  }
  return 0;
}
