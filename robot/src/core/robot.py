#!/usr/bin/env pybricks-micropython

from pybricks.hubs import EV3Brick
from pybricks.parameters import Button, Color, Port
from pybricks.tools import wait

import threading

from .control import PidController
from .device_managers import (ColorSensorManager, DeviceManager,
                              GyroSensorManager, MotorManager)
from .tools import RoboticTools, Parameters


class MbRobot():
    """
    Control an FLL robot
    Allows more complex control to robots such as: (1) Smooth acceleration and deceleration based on a PID control,
    (2) Precise turns using a gyro sensor, (3) Distance control based on the lines that can be found on the field,
    (4) Asynchronous control of the robot movement, (5) Stall detection
    """
    def __init__(self):
        self.Tools = RoboticTools(wheel_diameter=6.24)

        self.Ev3 = EV3Brick()
        self.Gyro = GyroSensorManager()
        self.Motors = MotorManager(exit_exec=lambda: Button.LEFT in self.Ev3.buttons.pressed())
        self.ColorSensors = ColorSensorManager()
        self.DeviceControl = DeviceManager()
        self.Parameters = Parameters()
            
        self.active = True # This will be used like a global switch
        self.setup_control(True, True, True)
        self.run_async(self.task_handler) # Task handler

    def setup_control(self, turn_control=False, run_control=False, line_follower_control=False):
        if turn_control:
            self.TurnSpeedControl = PidController(6, 0.15)
        if run_control:
            self.RunSpeedControl = PidController(3, 0.17, 0)
            self.RunHeadingControl = PidController(15, 0.1, 0)
        if line_follower_control:
            self.LineFollowerSpeedControl = PidController(1.4, 0, 0)
            self.LineFollowerHeadingControl = PidController(3, 0, 0.4)

    def task_handler(self):
        """
        Stop any movement the robot is performing by pressing the LEFT button of the ev3 brick
        """
        # This is gonna run asynchronously, works like a master switch
        while True:
            if Button.LEFT in self.Ev3.buttons.pressed(): 
                self.active = False
            wait(10)

    def turn(self, 
            angle, 
            speed_kp=None, 
            speed_ki=None, 
            speed_kd=None, 
            min_speed=None,
            max_speed=None,
            exit_exec=lambda: False):  
        """
        Turn using a gyro sensor

        Args:
            angle (int): Angle in degrees to the which the robot is gonna turn to
            speed_kp (int, float): Proportional gain for the speed control
            speed_ki (int, float): Integral gain for the speed control
            speed_kd (int, float): Derivate gain for the speed control
            exit_exec (Function): Function that returns True or False, the robot will stop if returns True
        """
        if self.active:

            self.Gyro.reset()
            self.TurnSpeedControl.reset()
            self.TurnSpeedControl.settings(speed_kp, speed_ki, speed_kd)

            moving = True
            while moving and self.active and not exit_exec():
                error = angle - self.Gyro.angle()

                self.TurnSpeedControl.execute(error)
                self.Motors.left_steering_motor.run(self.TurnSpeedControl.output)
                self.Motors.right_steering_motor.run(-self.TurnSpeedControl.output)

                if -2 < error < 2:
                    moving = False

            self.Motors.left_steering_motor.hold()
            self.Motors.right_steering_motor.hold()

            self.setup_control(turn_control=True)

    def drive(self, 
            distance, 
            orientation=0, 
            min_speed=90, 
            max_speed=800, 
            speed_kp=None, 
            speed_ki=None, 
            speed_kd=None, 
            heading_kp=None, 
            heading_ki=None, 
            heading_kd=None, 
            exit_exec=lambda: False):

        """
        Accelerate and decelerate as it gets towards its objetive while detecting if it got stalled
        
        Args:
            distance (int, float): Distance to move
            orientation (int, float, Function): The orientation the robot is going to follow, it can also be a function that returns a number
            min_speed (int, float): Minimun speed the robot is going to achieve
            max_speed (int, float): Maximun speed the robot is going to achieve
            speed_kp (int, float): Proportional gain for the speed control
            speed_ki (int, float): Integral gain for the speed control
            speed_kd (int, float): Derivative gain for the speed control
            heading_kp (int, float): Proportional gain for the speed control
            heading_ki (int, float): Integral gain for the speed control
            heading_kd (int, float): Derivative gain for the speed control
            exit_exec (Function): Function that returns True or False, the robots stops if returns True
        """
       
        if self.active:

            self.Gyro.reset()
            self.Motors.left_steering_motor.reset_angle()
            self.Motors.right_steering_motor.reset_angle()
            
            self.RunSpeedControl.reset()
            self.RunSpeedControl.settings(speed_kp, speed_ki, speed_kd)

            self.RunHeadingControl.reset()
            self.RunHeadingControl.settings(heading_kp, heading_ki, heading_kd)


            # This allows that anything can control the robot heading, by default it would use the gyro sensor to control the heading
            # but you can also pass a function that returns a number so that it uses that function to control the heading
            # e.g:
            #   orientation = lambda: sensor.reflection() - line_color => this would be for a line follower
            #   orientation = 4 => would make the robot move heading slightly to the right
            heading_error = (lambda: orientation - self.Gyro.angle()) if not callable(orientation) else orientation

            distance_dg = self.Tools.cm_to_degrees(distance)
            min_speed = abs(min_speed) * (-1 if distance < 0 else 1) 
            max_speed = abs(max_speed) * (-1 if distance < 0 else 1) 
            moved_enough = False
            moving = True
            while moving and self.active and not exit_exec():
                motors_dg = (self.Motors.right_steering_motor.angle() + self.Motors.left_steering_motor.angle()) / 2

                if abs(motors_dg) < abs(distance_dg)/2:
                    speed_error = distance_dg - (distance_dg - motors_dg)
                else:
                    speed_error = distance_dg - motors_dg
                    moved_enough = True

                self.RunHeadingControl.execute(heading_error())
                self.RunSpeedControl.execute(speed_error)

                if abs(self.RunSpeedControl.output) < abs(min_speed):
                    self.RunSpeedControl.output = min_speed
                elif abs(self.RunSpeedControl.output) > abs(max_speed):
                    self.RunSpeedControl.output = max_speed 
                
                self.Motors.left_steering_motor.run(self.RunSpeedControl.output)
                self.Motors.right_steering_motor.run(self.RunSpeedControl.output - self.RunHeadingControl.output)

                # When the robot has moved at least halfway
                if moved_enough:
                    # stop if the robot either reached the target distance or got stalled
                    if (abs(motors_dg) >= abs(distance_dg) - 20 or 
                        self.Motors.left_steering_motor.is_stalled(min_speed) or 
                        self.Motors.right_steering_motor.is_stalled(min_speed)):
                        moving = False

            self.Motors.left_steering_motor.brake()
            self.Motors.right_steering_motor.brake()
            self.setup_control(run_control=True)

    def follow_line(self, 
                    sensor, 
                    distance, 
                    target_value=None,
                    min_speed=None, 
                    max_speed=None, 
                    speed_kp=None,
                    speed_ki=None,
                    speed_kd=None,
                    heading_kp=None,
                    heading_ki=None,
                    heading_kd=None,
                    exit_exec=lambda: False):

        """
        Follow a line

        Args:
            sensor (ColorSensor, MbColorSensor): The sensor that will follow the line
            distance (int, float): Distance to move
            target_value (int): Value to follow with the sensor, will use the calibration file if stays as "default"
            min_speed (int, float): Minimun speed the robot is going to achieve
            max_speed (int, float): Maximun speed the robot is going to achieve
            speed_kp (int, float): Proportional gain for the speed control
            speed_ki (int, float): Integral gain for the speed control
            speed_kd (int, float): Derivative gain for the speed control
            heading_kp (int, float): Proportional gain for the speed control
            heading_ki (int, float): Integral gain for the speed control
            heading_kd (int, float): Derivative gain for the speed control
            exit_exec (Function): Function that returns True or False, the robots stops if returns True
        """

        if self.active:
            # value between the white and the black line
            target_value = self.ColorSensors.calibration_log()[0] if target_value == None else target_value
                
            self.LineFollowerSpeedControl.reset()
            self.LineFollowerSpeedControl.settings(speed_kp, speed_ki, speed_kd)

            self.LineFollowerHeadingControl.reset()
            self.LineFollowerHeadingControl.settings(heading_kp, heading_ki, heading_kd)
            
            self.drive(distance, 
                    orientation=lambda: sensor.reflection() - target_value, # heading control
                    min_speed=90, 
                    max_speed=800, 
                    speed_kp=self.LineFollowerSpeedControl.kp, 
                    speed_ki=self.LineFollowerSpeedControl.ki, 
                    speed_kd=self.LineFollowerSpeedControl.kd, 
                    heading_kp=self.LineFollowerHeadingControl.kp, 
                    heading_ki=self.LineFollowerHeadingControl.ki, 
                    heading_kd=self.LineFollowerHeadingControl.kd,
                    exit_exec=exit_exec)

            self.setup_control(line_follower_control=True)
            
    def drive_to_line(self, 
                    distance,
                    color="WHITE", 
                    sensor=None, 
                    orientation=0, 
                    speed_kp=None, 
                    speed_ki=None, 
                    speed_kd=None, 
                    heading_kp=None, 
                    heading_ki=None, 
                    heading_kd=None, 
                    min_speed=90, 
                    max_speed=800,
                    exit_exec=lambda: False):

        """
        Move the robot over a distance but will stop before if finds a line

        Args:
            sensor (ColorSensor, MbColorSensor): The sensor to use to detect the line
            distance (int, float): Distance to move
            color (str): Color of the line, should be either WHITE or BLACK
            orientation (int, float, Function): The orientation the robot is going to follow, it can also be a function that returns a number
            min_speed (int, float): Minimun speed the robot is going to achieve
            max_speed (int, float): Maximun speed the robot is going to achieve
            speed_kp (int, float): Proportional gain for the speed control
            speed_ki (int, float): Integral gain for the speed control
            speed_kd (int, float): Derivative gain for the speed control
            heading_kp (int, float): Proportional gain for the speed control
            heading_ki (int, float): Integral gain for the speed control
            heading_kd (int, float): Derivative gain for the speed control
            exit_exec (Function): Function that returns True or False, the robots stops if returns True
        """

        if self.active:
            sensor = self.ColorSensors.left_sensor if sensor == None else sensor
            colors = self.ColorSensors.calibration_log()

            if color.upper() == "WHITE":
                exit_exec = lambda: sensor.reflection() > colors[0] - 7 # white value from calib file
            elif color.upper() == "BLACK":
                exit_exec = lambda: sensor.reflection() < colors[1] + 5 # black value from calib file
            else:
                raise Exception("Invalid color for self.run_to_line()")
                            
            self.drive(distance, 
                    orientation=orientation, 
                    min_speed=min_speed, 
                    max_speed=max_speed, 
                    speed_kp=speed_kp, 
                    speed_ki=speed_ki, 
                    speed_kd=speed_kd, 
                    heading_kp=heading_kp, 
                    heading_ki=heading_ki, 
                    heading_kd=heading_kd,
                    exit_exec=exit_exec) # Check if the robot reached a white line

    def square_line(self, 
                    forward=True,
                    speed=170, 
                    color="WHITE"):

        """
        Use a line to correct the robot orientation

        Args:
            forward (bool): The robot will move forward if set to True else Backwards
            speed (int): Speed to move while squaring with the line
            color (str): Color of the line to square with

        Note:
            The sign of the speed parameter doesnt matters, all that matters is the forward parameter
        """

        if self.active:
            speed = abs(speed) * (1 if forward else -1)

            colors = self.ColorSensors.calibration_log()
            white_value = colors[0] - 10
            black_value = colors[1] + 5

            if color.upper() == "WHITE":
                left_steering_motor_exit_exec = lambda: self.ColorSensors.left_sensor.reflection() > white_value
                right_steering_motor_exit_exec = lambda: self.ColorSensors.right_sensor.reflection() > white_value
            elif color.upper() == "BLACK":
                left_steering_motor_exit_exec = lambda: self.ColorSensors.left_sensor.reflection() < black_value
                right_steering_motor_exit_exec = lambda: self.ColorSensors.right_sensor.reflection() < black_value
            else:
                raise Exception("Invalid color for Robot.square_line()")
                
            for repetition in range(2):
                self.Motors.left_steering_motor.run(speed)
                self.Motors.right_steering_motor.run(speed)
                left_ok = False
                right_ok = False
                while self.active:
                    # Keep moving the left motor until it reaches the line
                    if left_steering_motor_exit_exec():
                        left_ok = True
                        self.Motors.left_steering_motor.hold()

                    # Keep moving the right motor until it reaches the line
                    if right_steering_motor_exit_exec():
                        right_ok = True
                        self.Motors.right_steering_motor.hold()

                    # If both sensors are on the line, go backwards and repeat the process one more time
                    if left_ok and right_ok:
                        if repetition == 0:
                            self.drive(-5 if speed > 0 else 5, speed_kp=1.2)
                        break

                if not self.active:
                    break

            self.Motors.left_steering_motor.hold()
            self.Motors.right_steering_motor.hold()


    def run_path(self, path): 
        """
        Move using a path with the following format: [MOVE_STRAIGHT, TURN, MOVE_STRAIGHT, TURN, ...]
        This is the same format that a Path object returns (refer to control.py)


        Args:
            path (Path): The path to follow
        """
        for i in range(len(path) - 1):
            self.run(path[i])
            if i < len(path) - 2:
                self.turn(path[i+1])

    def run_async(self, target, args=[]):
        """
        Create a thread and runs a function in that thread

        Args:
            target (Function): Function to perform on the thread
            args (List): Arguments of the function, if they exist
        """
        threading.Thread(target=target, args=args).start()

    def pause(self, button_to_exit=Button.UP):
        """
        Pause the robot until you press a Button

        Args:
            button_to_exit (Button): What button will resume this pause
        """
        self.Ev3.light.on(Color.RED)
        while True:
            if button_to_exit in self.Ev3.buttons.pressed():
                break
        self.Ev3.light.on(Color.GREEN)

    def wait(self, msec):
        wait(msec)
