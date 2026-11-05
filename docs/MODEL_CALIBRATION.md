# Crazyflie model calibration status

The pinned Menagerie Crazyflie 2 model is a useful simulation starting point, not a calibrated physical digital twin. Its [upstream description](https://github.com/google-deepmind/mujoco_menagerie/tree/98a70c569c4c1b6da467a20012f766ee1f8dc521/bitcraze_crazyflie_2) explicitly says the combined thrust and body-moment control ranges are arbitrary and need tuning.

The model specifies 0.027 kg mass and uses a thrust command of 0.26487 N for level hover under 9.81 m/s² gravity. Its nominal thrust range is 0 to 0.35, and its three moment controls use -1 to 1 with a gear factor of -0.00001. These are properties of this model, not measured operating limits of a particular drone. A [Crazyflie 2.0 paper hosted by Bitcraze](https://www.bitcraze.io/papers/giernacki_draft_crazyflie2.0.pdf) describes a 27 g vehicle and the motor/propeller configuration, but that alone does not calibrate the complete actuator response.

Before treating the calibration gate as passed:

1. Identify an applicable Crazyflie 2.0 motor, propeller, battery, and loading configuration, with traceable thrust and moment measurements or model parameters.
2. Implement and document actuator limits, allocation, dynamics, and any lag or uncertainty that the chosen sources support. Distinguish directly sourced parameters from assumptions.
3. Exercise hover and perturbed tracking against pinned expected behavior, including saturation and repeatability checks on the deployed architecture.
4. Record model, source, solver, and scenario hashes. Treat remaining unmeasured parameters as uncertainty and keep simulation conclusions within that scope.

The feasibility controller and its altitude scenarios use the stock model and provisional bounds. They establish software behavior only.
