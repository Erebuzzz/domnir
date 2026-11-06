# Bitcraze Crazyflie 2.0 3D Asset Specification

## Model Overview
- Plant Platform: Bitcraze Crazyflie 2.0 open-source quadrotor
- Geometry Source: CAD meshes from MuJoCo Menagerie (Apache 2.0 / Bitcraze AB)
- Dimensions: 92 mm x 92 mm motor-to-motor span, ~105 mm rotor tip span, 29 mm height
- Mass Calibration: 27.0 g nominal dry mass with 240 mAh LiPo battery
- Coordinate Frame: Z-up, forward +X, left +Y, right -Y

## Hierarchy
- `DroneRoot` (Anchor)
  - `Frame_PCB`: Matte black FR4 circuit board frame with gold traces
  - `Motors`: Brushed metallic chrome cylindrical coreless DC motors (7x16mm)
  - `Mounts_Battery`: White injection-molded motor mount brackets and LiPo battery
  - `GoldTraces_Antenna`: Integrated 2.4 GHz meandered inverted-F antenna and test pads
  - `Connectors`: Expansion headers and battery retention clips
  - `RotorFL`: Front-Left counter-clockwise propeller (pivot centered at spin axis)
  - `RotorFR`: Front-Right clockwise propeller (pivot centered at spin axis)
  - `RotorRL`: Rear-Left clockwise propeller (pivot centered at spin axis)
  - `RotorRR`: Rear-Right counter-clockwise propeller (pivot centered at spin axis)

## Deliverables
- `crazyflie_2.blend`: Source authoring file with materials, pivots, and hierarchy
- `crazyflie_2.glb`: glTF binary runtime asset optimized for WebGL / Three.js
- `crazyflie_ragnarok_dawn.png`: High-resolution render with warm sunlight and contact shadow
- `crazyflie_ragnarok_dusk.png`: High-resolution render with cool obsidian/cyan lighting and contact shadow
