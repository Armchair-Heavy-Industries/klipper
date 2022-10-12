# Code for handling the kinematics of polar robots
#
# Copyright (C) 2018-2021  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, math
import stepper

def distance(p1, p2):
    return math.sqrt(((p2[0] - p1[0]) ** 2) + ((p2[1] - p1[1]) ** 2))
    
def sqrdistance(p1, p2):
    return ((p2[0] - p1[0]) ** 2) + ((p2[1] - p1[1]) ** 2)


def crosses_point(checkpoint, p1, p2):
    # check if check point lies on the line between p1 and p2
    return sqrdistance(checkpoint, p1) <= sqrdistance(p1, p2) and sqrdistance(
        checkpoint, p2
    ) <= sqrdistance(p1, p2)

def distance_point_to_line(p0, p1, p2):
    return (
        abs(
           ((p2[0] - p1[0]) * (p1[1] - p0[1]))
           - ((p1[0] - p0[0]) * (p2[1] - p1[1]))
        )
        / distance(p1, p2)
    )
class PolarXZKinematics:
    def __init__(self, toolhead, config):
        # Setup axis steppers
        stepper_bed = stepper.PrinterStepper(config.getsection('stepper_bed'),
                units_in_radians=True)
        rail_x = stepper.PrinterRail(config.getsection('stepper_x'))
        rail_z = stepper.PrinterRail(config.getsection('stepper_z'))
        stepper_bed.setup_itersolve('polarxz_stepper_alloc', b'a')
        rail_x.setup_itersolve('polarxz_stepper_alloc', b'+')
        rail_z.setup_itersolve('polarxz_stepper_alloc', b'-')
        self.rails = [rail_x, rail_z]
        self.steppers = [stepper_bed] + [
                s for r in self.rails for s in r.get_steppers()
        ]
        for s in self.get_steppers():
            s.set_trapq(toolhead.get_trapq())
            toolhead.register_step_generator(s.generate_steps)
        config.get_printer().register_event_handler("stepper_enable:motor_off",
                self._motor_off)
        # Setup boundary checks
        max_velocity, max_accel = toolhead.get_max_velocity()
        self.max_rotational_velocity = config.getfloat('max_rotational_velocity', max_velocity, above=0., maxval=max_velocity)
        self.max_rotational_accel = config.getfloat('max_rotational_accel', max_accel, above=0., maxval=max_accel)
        self.max_z_velocity = config.getfloat('max_z_velocity', max_velocity,
                above=0., maxval=max_velocity)
        self.max_z_accel = config.getfloat('max_z_accel', max_accel, above=0.,
                maxval=max_accel)
        self.limit_z = (1.0, -1.0)
        self.limit_xy2 = -1.
        max_xy = self.rails[0].get_range()[1]
        min_z, max_z = self.rails[1].get_range()
        self.axes_min = toolhead.Coord(-max_xy, -max_xy, min_z, 0.)
        self.axes_max = toolhead.Coord(max_xy, max_xy, max_z, 0.)
    def get_steppers(self):
        return list(self.steppers)
    def calc_position(self, stepper_positions):
        bed_angle = stepper_positions[self.steppers[0].get_name()]
        x_pos = stepper_positions[self.rails[0].get_name()]
        z_pos = stepper_positions[self.rails[1].get_name()]
        return [[(0.5 * ((math.cos(bed_angle) * x_pos)- z_pos)),
            math.sin(bed_angle) * x_pos, (0.5 * (x_pos + z_pos))]]
    def set_position(self, newpos, homing_axes):
        for s in self.steppers:
            s.set_position(newpos)
        if 2 in homing_axes:
            self.limit_z = self.rails[1].get_range()
        if 0 in homing_axes and 1 in homing_axes:
            self.limit_xy2 = self.rails[0].get_range()[1]**2
    def note_z_not_homed(self):
        # Helper for Safe Z Home
        self.limit_z = (1.0, -1.0)
    def _home_axis(self, homing_state, axis, rail):
        # Determine movement
        position_min, position_max = rail.get_range()
        hi = rail.get_homing_info()
        homepos = [None, None, None, None]
        homepos[axis] = hi.position_endstop
        if axis == 0:
            homepos[1] = 0.
        forcepos = list(homepos)
        if hi.positive_dir:
            forcepos[axis] -= hi.position_endstop - position_min
        else:
            forcepos[axis] += position_max - hi.position_endstop
        # Perform homing
        homing_state.home_rails([rail], forcepos, homepos)
    def home(self, homing_state):
        # Always home XY together
        homing_axes = homing_state.get_axes()
        home_xy = 0 in homing_axes or 1 in homing_axes
        home_z = 2 in homing_axes
        updated_axes = []
        if home_xy:
            updated_axes = [0, 1]
        if home_z:
            updated_axes.append(2)
        homing_state.set_axes(updated_axes)
        # Do actual homing
        if home_xy:
            self._home_axis(homing_state, 0, self.rails[0])
            self._home_axis(homing_state, 1, self.rails[0])
        if home_z:
            self._home_axis(homing_state, 2, self.rails[1])
    def home2(self, homing_state):
        # Each axis is homed independently and in order
        homing_axes = homing_state.get_axes()
        home_xy = 0 in homing_axes or 1 in homing_axes
        home_z = 2 in homing_axes
        for axis in homing_state.get_axes():
            if axis == 1:
                next
            rail = self.rails[axis]
            # Determine movement
            position_min, position_max = rail.get_range()
            hi = rail.get_homing_info()
            homepos = [None, None, None, None]
            homepos[axis] = hi.position_endstop
            forcepos = list(homepos)
            if hi.positive_dir:
                forcepos[axis] -= 1.5 * (hi.position_endstop - position_min)
            else:
                forcepos[axis] += 1.5 * (position_max - hi.position_endstop)
            # Perform homing
            homing_state.home_rails([rail], forcepos, homepos)
    def _motor_off(self, print_time):
        self.limit_z = (1.0, -1.0)
        self.limit_xy2 = -1.
    def check_move(self, move):
        end_pos = move.end_pos
        xy2 = end_pos[0]**2 + end_pos[1]**2
        if xy2 > self.limit_xy2:
            if self.limit_xy2 < 0.:
                raise move.move_error("Must home axis first")
            raise move.move_error()
        # Limit the maximum acceleration against the rotational distance theta
        # TODO: Optimize with code from the chelper?
        if move.axes_d[0] or move.axes_d[1]:
            pi = 3.1415
            bed_center = (0, 0) # TODO: Cartesian X,Y of bed center
            bed_radius = distance(bed_center, (bed_center[0], self.axes_min[0]))
            start_xy = move.start_pos
            end_xy = move.end_pos
            start_radius = distance(bed_center, start_xy)
            # move_radius = distance_point_to_line(bed_center, start_xy, end_xy)
            end_radius = distance(bed_center, end_xy)
            scale = 2 * math.pi * ( min(start_radius, end_radius) / bed_radius )
            move.limit_speed(self.max_rotational_accel, self.max_rotational_velocity * scale)
        if move.axes_d[2]:
            if end_pos[2] < self.limit_z[0] or end_pos[2] > self.limit_z[1]:
                if self.limit_z[0] > self.limit_z[1]:
                    raise move.move_error("Must home axis first")
                raise move.move_error()
            # Move with Z - update velocity and accel for slower Z axis
            z_ratio = move.move_d / abs(move.axes_d[2])
            move.limit_speed(self.max_z_velocity * z_ratio,
                             self.max_z_accel * z_ratio)
    def segment_move(self, move):
        # detect if move crosses 0,0
        if crosses_point((0, 0), move.start_pos, move.end_pos):
            if move.start_pos[0] == 0 and move.end_pos[0] == 0:
                # if we are moving directly down X == 0
                move_options = (
                    (0, 0.005),  # above 0,0
                    (0, -0.005),  # below 0,0
                )
            elif move.start_pos[1] == 0 and move.end_pos[1] == 0:
                # if we are moving directly down Y == 0
                move_options = (
                    (0.005, 0),  # right of 0,0
                    (-0.005, 0),  # left of 0,0
                )
            else:
                move_options = (
                    (0, 0.005),  # above 0,0
                    (0.005, 0),  # right of 0,0
                    (0, -0.005),  # below 0,0
                    (-0.005, 0),  # left of 0,0
                )
            closest_to_start = 100000
            closest_to_end = 100000
            closest_end_pos = None
            closest_start_pos = None
            for move_option in move_options:
                dist_to_end = distance(move_option, move.end_pos)
                dist_to_start = distance(move_option, move.start_pos)
                if dist_to_end < closest_to_end:
                    closest_to_end = dist_to_end
                    closest_end_pos = move_option
                if dist_to_start < closest_to_start:
                    closest_to_start = dist_to_start
                    closest_start_pos = move_option
            # create a move from start to closest_start_pos
            move1 = (move.start_pos, closest_start_pos)
            move2 = (closest_start_pos, closest_end_pos)
            move3 = (closest_end_pos, move.end_pos)
            return [move1, move2, move3]
        else:
            return None
    def get_status(self, eventtime):
        xy_home = "xy" if self.limit_xy2 >= 0. else ""
        z_home = "z" if self.limit_z[0] <= self.limit_z[1] else ""
        return {
            'homed_axes': xy_home + z_home,
            'axis_minimum': self.axes_min,
            'axis_maximum': self.axes_max,
        }

def load_kinematics(toolhead, config):
    return PolarXZKinematics(toolhead, config)
