
#!/usr/bin/env python3

import time
from xarm.wrapper import XArmAPI

#Instantiation API
arm = XArmAPI('192.168.0.240')
time.sleep(0.5)


#clean error and warn
if arm.warn_code != 0:
    arm.clean_warn()
if arm.error_code != 0:
    arm.clean_error()

#Enable the robot
arm.motion_enable(enable=True)

#set mode and state
arm.set_mode(0)
arm.set_state(0)


arm.set_position(x=370, y=50, z=400, roll=180, pitch=0, yaw=0, speed=100, wait=True)
arm.disconnect()