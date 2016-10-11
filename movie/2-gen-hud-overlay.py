#!/usr/bin/python

# find our custom built opencv first
import sys
sys.path.insert(0, "/usr/local/lib/python2.7/site-packages/")

import argparse
import cv2
import datetime
import ephem
import math
import fractions
from matplotlib import pyplot as plt 
import navpy
import numpy as np
import os
import pyexiv2
import re
#from scipy.interpolate import InterpolatedUnivariateSpline
from scipy import interpolate # strait up linear interpolation, nothing fancy

from props import PropertyNode, getNode
import props_json

sys.path.append('../lib')
import transformations

# a helpful constant
d2r = math.pi / 180.0

parser = argparse.ArgumentParser(description='correlate movie data to flight data.')
parser.add_argument('--movie', required=True, help='original movie')
parser.add_argument('--scale', type=float, default=1.0, help='scale input')
parser.add_argument('--resample-hz', type=float, default=30.0, help='resample rate (hz)')
parser.add_argument('--apm-log', help='APM tlog converted to csv')
parser.add_argument('--aura-dir', help='Aura flight log directory')
parser.add_argument('--stop-count', type=int, default=1, help='how many non-frames to absorb before we decide the movie is over')
parser.add_argument('--plot', help='Plot stuff at the end of the run')
args = parser.parse_args()

r2d = 180.0 / math.pi
counter = 0
stop_count = 0

# pathname work
abspath = os.path.abspath(args.movie)
filename, ext = os.path.splitext(abspath)
movie_log = filename + ".csv"
movie_config = filename + ".json"
# combinations that seem to work on linux
# ext = avi, fourcc = MJPG
# ext = avi, fourcc = XVID
# ext = mov, fourcc = MP4V

tmp_movie = filename + "_tmp.mov"
output_movie = filename + "_hud.mov"

# load config file if it exists
config = PropertyNode()
props_json.load(movie_config, config)
cam_yaw = config.getFloat('cam_yaw_deg')
cam_pitch = config.getFloat('cam_pitch_deg')
cam_roll = config.getFloat('cam_roll_deg')

# load movie log
movie = []
with open(movie_log, 'rb') as f:
    for line in f:
        movie.append( re.split('[,\s]+', line.rstrip()) )

flight_imu = []
flight_gps = []
flight_filter = []
flight_air = []
flight_pilot = []
flight_ap = []
last_imu_time = -1
last_gps_time = -1

if args.apm_log:
    # load APM flight log
    agl = 0.0
    with open(args.apm_log, 'rb') as f:
        for line in f:
            tokens = re.split('[,\s]+', line.rstrip())
            if tokens[7] == 'mavlink_attitude_t':
                timestamp = float(tokens[9])/1000.0
                print timestamp
                if timestamp > last_imu_time:
                    flight_imu.append( [timestamp,
                                        float(tokens[17]), float(tokens[19]),
                                        float(tokens[21]),
                                        float(tokens[11]), float(tokens[13]),
                                        float(tokens[15])] )
                    last_imu_time = timestamp
                else:
                    print "ERROR: IMU time went backwards:", timestamp, last_imu_time
            elif tokens[7] == 'mavlink_gps_raw_int_t':
                timestamp = float(tokens[9])/1000000.0
                if timestamp > last_gps_time - 1.0:
                    flight_gps.append( [timestamp,
                                        float(tokens[11]) / 10000000.0,
                                        float(tokens[13]) / 10000000.0,
                                        float(tokens[15]) / 1000.0,
                                        agl] )
                    last_gps_time = timestamp
                else:
                    print "ERROR: GPS time went backwards:", timestamp, last_gps_time
            elif tokens[7] == 'mavlink_terrain_report_t':
                agl = float(tokens[15])
elif args.aura_dir:
    # load Aura flight log
    imu_file = args.aura_dir + "/imu-0.txt"
    gps_file = args.aura_dir + "/gps-0.txt"
    filter_file = args.aura_dir + "/filter-0.txt"
    air_file = args.aura_dir + "/air-0.txt"
    pilot_file = args.aura_dir + "/pilot-0.txt"
    ap_file = args.aura_dir + "/ap-0.txt"
    
    last_time = 0.0
    with open(imu_file, 'rb') as f:
        for line in f:
            tokens = re.split('[,\s]+', line.rstrip())
            timestamp = float(tokens[0])
            if timestamp > last_time:
                flight_imu.append( [tokens[0], tokens[1], tokens[2],
                                    tokens[3], 0.0, 0.0, 0.0] )
            else:
                print "ERROR: time went backwards:", timestamp, last_time
            last_time = timestamp

    last_time = 0.0
    with open(gps_file, 'rb') as f:
        for line in f:
            #print line
            tokens = re.split('[,\s]+', line.rstrip())
            timestamp = float(tokens[0])
            #print timestamp, last_time
            if timestamp > last_time:
                flight_gps.append( [tokens[0], tokens[1], tokens[2],
                                    tokens[3], tokens[7]] )
            else:
                print "ERROR: time went backwards:", timestamp, last_time
            last_time = timestamp

    last_time = 0.0
    with open(filter_file, 'rb') as f:
        for line in f:
            #print line
            tokens = re.split('[,\s]+', line.rstrip())
            timestamp = float(tokens[0])
            #print timestamp, last_time
            if timestamp > last_time:
                yaw = float(tokens[9])
                yaw_x = math.cos(yaw*d2r)
                yaw_y = math.sin(yaw*d2r)
                flight_filter.append( [tokens[0],
                                       tokens[1], tokens[2], tokens[3],
                                       tokens[4], tokens[5], tokens[6],
                                       tokens[7], tokens[8], tokens[9],
                                       yaw_x, yaw_y] )
            else:
                print "ERROR: time went backwards:", timestamp, last_time
            last_time = timestamp

    last_time = 0.0
    with open(air_file, 'rb') as f:
        for line in f:
            #print line
            tokens = re.split('[,\s]+', line.rstrip())
            timestamp = float(tokens[0])
            #print timestamp, last_time
            if timestamp > last_time:
                flight_air.append( [tokens[0], tokens[1], tokens[2],
                                    tokens[3]] )
            else:
                print "ERROR: time went backwards:", timestamp, last_time
            last_time = timestamp
            
    last_time = 0.0
    with open(pilot_file, 'rb') as f:
        for line in f:
            #print line
            tokens = re.split('[,\s]+', line.rstrip())
            timestamp = float(tokens[0])
            #print timestamp, last_time
            if timestamp > last_time:
                flight_pilot.append( tokens )
            else:
                print "ERROR: time went backwards:", timestamp, last_time
            last_time = timestamp
            
    last_time = 0.0
    with open(ap_file, 'rb') as f:
        for line in f:
            #print line
            tokens = re.split('[,\s]+', line.rstrip())
            timestamp = float(tokens[0])
            #print timestamp, last_time
            if timestamp > last_time:
                hdg = float(tokens[1])
                hdg_x = math.cos(hdg*d2r)
                hdg_y = math.sin(hdg*d2r)
                tokens.append(hdg_x)
                tokens.append(hdg_y)
                flight_ap.append( tokens )
            else:
                print "ERROR: time went backwards:", timestamp, last_time
            last_time = timestamp
else:
    print "No flight log specified, cannot continue."
    quit()
    
# resample movie data
movie = np.array(movie, dtype=float)
movie_interp = []
x = movie[:,0]
movie_spl_roll = interpolate.interp1d(x, movie[:,2], bounds_error=False, fill_value=0.0)
movie_spl_pitch = interpolate.interp1d(x, movie[:,3], bounds_error=False, fill_value=0.0)
movie_spl_yaw = interpolate.interp1d(x, movie[:,4], bounds_error=False, fill_value=0.0)
xmin = x.min()
xmax = x.max()
print "movie range = %.3f - %.3f (%.3f)" % (xmin, xmax, xmax-xmin)
time = xmax - xmin
for x in np.linspace(xmin, xmax, time*args.resample_hz):
    movie_interp.append( [x, movie_spl_roll(x)] )
print "movie len:", len(movie_interp)

# resample flight data
flight_imu = np.array(flight_imu, dtype=float)
flight_interp = []
x = flight_imu[:,0]
flight_imu_p = interpolate.interp1d(x, flight_imu[:,1], bounds_error=False, fill_value=0.0)
flight_imu_q = interpolate.interp1d(x, flight_imu[:,2], bounds_error=False, fill_value=0.0)
flight_imu_r = interpolate.interp1d(x, flight_imu[:,3], bounds_error=False, fill_value=0.0)
if args.apm_log:
    y_spline = flight_imu_r
elif args.aura_dir:
    y_spline = flight_imu_p
xmin = x.min()
xmax = x.max()
print "flight range = %.3f - %.3f (%.3f)" % (xmin, xmax, xmax-xmin)
time = xmax - xmin
for x in np.linspace(xmin, xmax, time*args.resample_hz):
    flight_interp.append( [x, y_spline(x)] )
print "flight len:", len(flight_interp)

flight_gps = np.array(flight_gps, dtype=np.float64)
x = flight_gps[:,0]
flight_gps_lat = interpolate.interp1d(x, flight_gps[:,1], bounds_error=False, fill_value=0.0)
flight_gps_lon = interpolate.interp1d(x, flight_gps[:,2], bounds_error=False, fill_value=0.0)
flight_gps_alt = interpolate.interp1d(x, flight_gps[:,3], bounds_error=False, fill_value=0.0)
flight_gps_unixtime = interpolate.interp1d(x, flight_gps[:,4], bounds_error=False, fill_value=0.0)

flight_filter = np.array(flight_filter, dtype=float)
x = flight_filter[:,0]
flight_filter_vn = interpolate.interp1d(x, flight_filter[:,4], bounds_error=False, fill_value=0.0)
flight_filter_ve = interpolate.interp1d(x, flight_filter[:,5], bounds_error=False, fill_value=0.0)
flight_filter_vd = interpolate.interp1d(x, flight_filter[:,6], bounds_error=False, fill_value=0.0)
flight_filter_roll = interpolate.interp1d(x, flight_filter[:,7], bounds_error=False, fill_value=0.0)
flight_filter_pitch = interpolate.interp1d(x, flight_filter[:,8], bounds_error=False, fill_value=0.0)
flight_filter_yaw = interpolate.interp1d(x, flight_filter[:,9], bounds_error=False, fill_value=0.0)
flight_filter_yaw_x = interpolate.interp1d(x, flight_filter[:,10], bounds_error=False, fill_value=0.0)
flight_filter_yaw_y = interpolate.interp1d(x, flight_filter[:,11], bounds_error=False, fill_value=0.0)

flight_air = np.array(flight_air, dtype=np.float64)
x = flight_air[:,0]
flight_air_speed = interpolate.interp1d(x, flight_air[:,3], bounds_error=False, fill_value=0.0)

flight_pilot = np.array(flight_pilot, dtype=np.float64)
x = flight_pilot[:,0]
flight_pilot_auto = interpolate.interp1d(x, flight_pilot[:,8], bounds_error=False, fill_value=0.0)

flight_ap = np.array(flight_ap, dtype=np.float64)
x = flight_ap[:,0]
flight_ap_hdg = interpolate.interp1d(x, flight_ap[:,1], bounds_error=False, fill_value=0.0)
flight_ap_hdg_x = interpolate.interp1d(x, flight_ap[:,8], bounds_error=False, fill_value=0.0)
flight_ap_hdg_y = interpolate.interp1d(x, flight_ap[:,9], bounds_error=False, fill_value=0.0)
flight_ap_roll = interpolate.interp1d(x, flight_ap[:,2], bounds_error=False, fill_value=0.0)
flight_ap_pitch = interpolate.interp1d(x, flight_ap[:,5], bounds_error=False, fill_value=0.0)
flight_ap_speed = interpolate.interp1d(x, flight_ap[:,7], bounds_error=False, fill_value=0.0)

# compute best correlation between movie and flight data logs
movie_interp = np.array(movie_interp, dtype=float)
flight_interp = np.array(flight_interp, dtype=float)
ycorr = np.correlate(movie_interp[:,1], flight_interp[:,1], mode='full')

# display some stats/info
max_index = np.argmax(ycorr)
print "max index:", max_index
shift = np.argmax(ycorr) - len(flight_interp)
print "shift (pos):", shift
start_diff = flight_interp[0][0] - movie_interp[0][0]
print "start time diff:", start_diff
time_shift = start_diff - (shift/args.resample_hz)
print "movie time shift:", time_shift

# estimate  tx, ty vs. r, q multiplier
tmin = np.amax( [np.amin(movie_interp[:,0]) + time_shift,
                np.amin(flight_interp[:,0]) ] )
tmax = np.amin( [np.amax(movie_interp[:,0]) + time_shift,
                np.amax(flight_interp[:,0]) ] )
print "overlap range (flight sec):", tmin, " - ", tmax

mqsum = 0.0
fqsum = 0.0
mrsum = 0.0
frsum = 0.0
count = 0
qratio = 1.0
for x in np.linspace(tmin, tmax, time*args.resample_hz):
    mqsum += abs(movie_spl_pitch(x-time_shift))
    mrsum += abs(movie_spl_yaw(x-time_shift))
    fqsum += abs(flight_imu_q(x))
    frsum += abs(flight_imu_r(x))
if fqsum > 0.001:
    qratio = mqsum / fqsum
if mrsum > 0.001:
    rratio = -mrsum / frsum
print "pitch ratio:", qratio
print "yaw ratio:", rratio

def compute_sun_moon_ned(lon_deg, lat_deg, alt_m, timestamp):
    d = datetime.datetime.utcfromtimestamp(timestamp)
    #d = datetime.datetime.utcnow()
    ed = ephem.Date(d)
    #print 'ephem time utc:', ed
    #print 'localtime:', ephem.localtime(ed)

    ownship = ephem.Observer()
    ownship.lon = '%.8f' % lon_deg
    ownship.lat = '%.8f' % lat_deg
    ownship.elevation = alt_m
    ownship.date = ed

    sun = ephem.Sun(ownship)
    moon = ephem.Moon(ownship)

    sun_ned = [ math.cos(sun.az), math.sin(sun.az), -math.sin(sun.alt) ]
    moon_ned = [ math.cos(moon.az), math.sin(moon.az), -math.sin(moon.alt) ]

    return sun_ned, moon_ned

def project_point(K, PROJ, ned):
    uvh = K.dot( PROJ.dot( [ned[0], ned[1], ned[2], 1.0] ).T )
    if uvh[2] > 0.1:
        uvh /= uvh[2]
        uv = ( int(np.squeeze(uvh[0,0])), int(np.squeeze(uvh[1,0])) )
        return uv
    else:
        return None

def draw_horizon(K, PROJ, ned, frame):
    divs = 10
    pts = []
    for i in range(divs + 1):
        a = (float(i) * 360/float(divs)) * d2r
        n = math.cos(a)
        e = math.sin(a)
        d = 0.0
        pts.append( [n, e, d] )

    for i in range(divs):
        p1 = pts[i]
        p2 = pts[i+1]
        uv1 = project_point(K, PROJ,
                            [ned[0] + p1[0], ned[1] + p1[1], ned[2] + p1[2]])
        uv2 = project_point(K, PROJ,
                            [ned[0] + p2[0], ned[1] + p2[1], ned[2] + p2[2]])
        if uv1 != None and uv2 != None:
            cv2.line(frame, uv1, uv2, (0,240,0), 1, cv2.CV_AA)

def ladder_helper(q0, a0, a1):
    q1 = transformations.quaternion_from_euler(-a1*d2r, -a0*d2r, 0.0, 'rzyx')
    q = transformations.quaternion_multiply(q1, q0)
    v = transformations.quaternion_transform(q, [1.0, 0.0, 0.0])
    uv = project_point(K, PROJ,
                        [ned[0] + v[0], ned[1] + v[1], ned[2] + v[2]])
    return uv

def draw_pitch_ladder(K, PROJ, ned, frame, yaw_rad):
    a1 = 2.0
    a2 = 8.0
    q0 = transformations.quaternion_about_axis(yaw_rad, [0.0, 0.0, -1.0])
    for a0 in range(5,35,5):
        # above horizon
        
        # right horizontal
        uv1 = ladder_helper(q0, a0, a1)
        uv2 = ladder_helper(q0, a0, a2)
        if uv1 != None and uv2 != None:
            cv2.line(frame, uv1, uv2, (0,240,0), 1, cv2.CV_AA)
            du = uv2[0] - uv1[0]
            dv = uv2[1] - uv1[1]
            uv = ( uv1[0] + int(1.25*du), uv1[1] + int(1.25*dv) )
            draw_label(frame, "%d" % a0, uv, font, 0.6, 1)
        # right tick
        uv1 = ladder_helper(q0, a0-0.5, a1)
        uv2 = ladder_helper(q0, a0, a1)
        if uv1 != None and uv2 != None:
            cv2.line(frame, uv1, uv2, (0,240,0), 1, cv2.CV_AA)
        # left horizontal
        uv1 = ladder_helper(q0, a0, -a1)
        uv2 = ladder_helper(q0, a0, -a2)
        if uv1 != None and uv2 != None:
            cv2.line(frame, uv1, uv2, (0,240,0), 1, cv2.CV_AA)
            du = uv2[0] - uv1[0]
            dv = uv2[1] - uv1[1]
            uv = ( uv1[0] + int(1.25*du), uv1[1] + int(1.25*dv) )
            draw_label(frame, "%d" % a0, uv, font, 0.6, 1)
        # left tick
        uv1 = ladder_helper(q0, a0-0.5, -a1)
        uv2 = ladder_helper(q0, a0, -a1)
        if uv1 != None and uv2 != None:
            cv2.line(frame, uv1, uv2, (0,240,0), 1, cv2.CV_AA)
            
        # below horizon
        
        # right horizontal
        uv1 = ladder_helper(q0, -a0, a1)
        uv2 = ladder_helper(q0, -a0-0.5, a2)
        if uv1 != None and uv2 != None:
            du = uv2[0] - uv1[0]
            dv = uv2[1] - uv1[1]
            for i in range(0,3):
                tmp1 = ( uv1[0] + int(0.375*i*du), uv1[1] + int(0.375*i*dv) )
                tmp2 = ( tmp1[0] + int(0.25*du), tmp1[1] + int(0.25*dv) )
                cv2.line(frame, tmp1, tmp2, (0,240,0), 1, cv2.CV_AA)
            uv = ( uv1[0] + int(1.25*du), uv1[1] + int(1.25*dv) )
            draw_label(frame, "%d" % a0, uv, font, 0.6, 1)

        # right tick
        uv1 = ladder_helper(q0, -a0+0.5, a1)
        uv2 = ladder_helper(q0, -a0, a1)
        if uv1 != None and uv2 != None:
            cv2.line(frame, uv1, uv2, (0,240,0), 1, cv2.CV_AA)
        # left horizontal
        uv1 = ladder_helper(q0, -a0, -a1)
        uv2 = ladder_helper(q0, -a0-0.5, -a2)
        if uv1 != None and uv2 != None:
            du = uv2[0] - uv1[0]
            dv = uv2[1] - uv1[1]
            for i in range(0,3):
                tmp1 = ( uv1[0] + int(0.375*i*du), uv1[1] + int(0.375*i*dv) )
                tmp2 = ( tmp1[0] + int(0.25*du), tmp1[1] + int(0.25*dv) )
                cv2.line(frame, tmp1, tmp2, (0,240,0), 1, cv2.CV_AA)
            uv = ( uv1[0] + int(1.25*du), uv1[1] + int(1.25*dv) )
            draw_label(frame, "%d" % a0, uv, font, 0.6, 1)
        # left tick
        uv1 = ladder_helper(q0, -a0+0.5, -a1)
        uv2 = ladder_helper(q0, -a0, -a1)
        if uv1 != None and uv2 != None:
            cv2.line(frame, uv1, uv2, (0,240,0), 1, cv2.CV_AA)

def rotate_pt(p, center, a):
    x = math.cos(a) * (p[0]-center[0]) - math.sin(a) * (p[1]-center[1]) + center[0]

    y = math.sin(a) * (p[0]-center[0]) + math.cos(a) * (p[1]-center[1]) + center[1]
    return (int(x), int(y))
    
def draw_vbars(K, PROJ, ned, frame, yaw_rad, pitch_rad, ap_roll, ap_pitch):
    color = (186, 85, 211)      # medium orchid
    size = 2
    a1 = 10.0
    a2 = 1.5
    a3 = 3.0
    q0 = transformations.quaternion_about_axis(yaw_rad, [0.0, 0.0, -1.0])
    a0 = ap_pitch

    # rotation point (about nose)
    rot = ladder_helper(q0, pitch_rad*r2d, 0.0)

    # center point
    tmp1 = ladder_helper(q0, a0, 0.0)
    center = rotate_pt(tmp1, rot, ap_roll*d2r)
    
    # right vbar
    tmp1 = ladder_helper(q0, a0-a3, a1)
    tmp2 = ladder_helper(q0, a0-a3, a1+a3)
    tmp3 = ladder_helper(q0, a0-a2, a1+a3)
    uv1 = rotate_pt(tmp1, rot, ap_roll*d2r)
    uv2 = rotate_pt(tmp2, rot, ap_roll*d2r)
    uv3 = rotate_pt(tmp3, rot, ap_roll*d2r)
    if uv1 != None and uv2 != None and uv3 != None:
        cv2.line(frame, center, uv1, color, size, cv2.CV_AA)
        cv2.line(frame, center, uv3, color, size, cv2.CV_AA)
        cv2.line(frame, uv1, uv2, color, size, cv2.CV_AA)
        cv2.line(frame, uv1, uv3, color, size, cv2.CV_AA)
        cv2.line(frame, uv2, uv3, color, size, cv2.CV_AA)
    # left vbar
    tmp1 = ladder_helper(q0, a0-a3, -a1)
    tmp2 = ladder_helper(q0, a0-a3, -a1-a3)
    tmp3 = ladder_helper(q0, a0-a2, -a1-a3)
    uv1 = rotate_pt(tmp1, rot, ap_roll*d2r)
    uv2 = rotate_pt(tmp2, rot, ap_roll*d2r)
    uv3 = rotate_pt(tmp3, rot, ap_roll*d2r)
    if uv1 != None and uv2 != None and uv3 != None:
        cv2.line(frame, center, uv1, color, size, cv2.CV_AA)
        cv2.line(frame, center, uv3, color, size, cv2.CV_AA)
        cv2.line(frame, uv1, uv2, color, size, cv2.CV_AA)
        cv2.line(frame, uv1, uv3, color, size, cv2.CV_AA)
        cv2.line(frame, uv2, uv3, color, size, cv2.CV_AA)

def draw_heading_bug(K, PROJ, ned, frame, ap_hdg):
    color = (186, 85, 211)      # medium orchid
    size = 2
    a = math.atan2(ve, vn)
    q0 = transformations.quaternion_about_axis(ap_hdg*d2r, [0.0, 0.0, -1.0])
    center = ladder_helper(q0, 0, 0)
    pts = []
    pts.append( ladder_helper(q0, 0, 2.0) )
    pts.append( ladder_helper(q0, 0.0, -2.0) )
    pts.append( ladder_helper(q0, 1.5, -2.0) )
    pts.append( ladder_helper(q0, 1.5, -1.0) )
    pts.append( center )
    pts.append( ladder_helper(q0, 1.5, 1.0) )
    pts.append( ladder_helper(q0, 1.5, 2.0) )
    for i, p in enumerate(pts):
        if p == None or center == None:
            return
        #else:
        #    pts[i] = rotate_pt(pts[i], center, -cam_roll*d2r)
    cv2.line(frame, pts[0], pts[1], color, size, cv2.CV_AA)
    cv2.line(frame, pts[1], pts[2], color, size, cv2.CV_AA)
    cv2.line(frame, pts[2], pts[3], color, size, cv2.CV_AA)
    cv2.line(frame, pts[3], pts[4], color, size, cv2.CV_AA)
    cv2.line(frame, pts[4], pts[5], color, size, cv2.CV_AA)
    cv2.line(frame, pts[5], pts[6], color, size, cv2.CV_AA)
    cv2.line(frame, pts[6], pts[0], color, size, cv2.CV_AA)
    #pts = np.array( pts, np.int32 )
    #pts = pts.reshape((-1,1,2))
    #cv2.polylines(frame, pts, True, color, size, cv2.CV_AA)

def draw_bird(K, PROJ, ned, frame, yaw_rad, pitch_rad, roll_rad):
    color = (50, 255, 255)     # yellow
    size = 2
    a1 = 10.0
    a2 = 3.0
    a2 = 3.0
    q0 = transformations.quaternion_about_axis(yaw_rad, [0.0, 0.0, -1.0])
    a0 = pitch_rad*r2d

    # center point
    center = ladder_helper(q0, pitch_rad*r2d, 0.0)
    
    # right vbar
    tmp1 = ladder_helper(q0, a0-a2, a1)
    tmp2 = ladder_helper(q0, a0-a2, a1-a2)
    uv1 = rotate_pt(tmp1, center, roll_rad)
    uv2 = rotate_pt(tmp2, center, roll_rad)
    if uv1 != None and uv2 != None:
        cv2.line(frame, center, uv1, color, size, cv2.CV_AA)
        cv2.line(frame, center, uv2, color, size, cv2.CV_AA)
        cv2.line(frame, uv1, uv2, color, size, cv2.CV_AA)
    # left vbar
    tmp1 = ladder_helper(q0, a0-a2, -a1)
    tmp2 = ladder_helper(q0, a0-a2, -a1+a2)
    uv1 = rotate_pt(tmp1, center, roll_rad)
    uv2 = rotate_pt(tmp2, center, roll_rad)
    if uv1 != None and uv2 != None:
        cv2.line(frame, center, uv1, color, size, cv2.CV_AA)
        cv2.line(frame, center, uv2, color, size, cv2.CV_AA)
        cv2.line(frame, uv1, uv2, color, size, cv2.CV_AA)

def draw_course(K, PROJ, ned, frame, vn, ve):
    color = (50, 255, 255)     # yellow
    size = 2
    a = math.atan2(ve, vn)
    q0 = transformations.quaternion_about_axis(a, [0.0, 0.0, -1.0])
    tmp1 = ladder_helper(q0, 0, 0)
    tmp2 = ladder_helper(q0, 1.5, 1.0)
    tmp3 = ladder_helper(q0, 1.5, -1.0)
    if tmp1 != None and tmp2 != None and tmp3 != None :
        uv2 = rotate_pt(tmp2, tmp1, -cam_roll*d2r)
        uv3 = rotate_pt(tmp3, tmp1, -cam_roll*d2r)
        cv2.line(frame, tmp1, uv2, color, size, cv2.CV_AA)
        cv2.line(frame, tmp1, uv3, color, size, cv2.CV_AA)

def draw_label(frame, label, uv, font, font_scale, thickness, horiz='center',
               vert='center'):
        size = cv2.getTextSize(label, font, font_scale, thickness)
        if horiz == 'center':
            u = uv[0] - (size[0][0] / 2)
        else:
            u = uv[0]
        if vert == 'above':
            v = uv[1]
        elif vert == 'below':
            v = uv[1] + size[0][1]
        elif vert == 'center':
            v = uv[1] + (size[0][1] / 2)
        uv = (u, v)
        cv2.putText(frame, label, uv, font, font_scale, (0,255,0),
                    thickness, cv2.CV_AA)

def draw_labeled_point(K, PROJ, frame, ned, label, scale=1, vert='above'):
    uv = project_point(K, PROJ, [ned[0], ned[1], ned[2]])
    if uv != None:
        cv2.circle(frame, uv, 5, (0,240,0), 1, cv2.CV_AA)
    if vert == 'above':
        uv = project_point(K, PROJ, [ned[0], ned[1], ned[2] - 0.02])
    else:
        uv = project_point(K, PROJ, [ned[0], ned[1], ned[2] + 0.02])
    if uv != None:
        draw_label(frame, label, uv, font, scale, 1, vert=vert)

def draw_lla_point(K, PROJ, frame, ned, lla, label):
    pt_ned = navpy.lla2ned( lla[0], lla[1], lla[2], ref[0], ref[1], ref[2] )
    rel_ned = [ pt_ned[0] - ned[0], pt_ned[1] - ned[1], pt_ned[2] - ned[2] ]
    dist = math.sqrt(rel_ned[0]*rel_ned[0] + rel_ned[1]*rel_ned[1]
                     + rel_ned[2]*rel_ned[2])
    m2sm = 0.000621371
    dist_sm = dist * m2sm
    if dist_sm <= 15.0:
        scale = 1.0 - dist_sm / 25.0
        if dist_sm <= 7.5:
            label += " (%.1f)" % dist_sm
        # normalize, and draw relative to aircraft ned so that label
        # separation works better
        rel_ned[0] /= dist
        rel_ned[1] /= dist
        rel_ned[2] /= dist
        draw_labeled_point(K, PROJ, frame,
                           [ned[0] + rel_ned[0], ned[1] + rel_ned[1],
                            ned[2] + rel_ned[2]],
                            label, scale=scale, vert='below')
    
def draw_compass_points(K, PROJ, ned, frame):
    # 30 Ticks
    divs = 12
    pts = []
    for i in range(divs):
        a = (float(i) * 360/float(divs)) * d2r
        n = math.cos(a)
        e = math.sin(a)
        uv1 = project_point(K, PROJ,
                            [ned[0] + n, ned[1] + e, ned[2] - 0.0])
        uv2 = project_point(K, PROJ,
                            [ned[0] + n, ned[1] + e, ned[2] - 0.02])
        if uv1 != None and uv2 != None:
            cv2.line(frame, uv1, uv2, (0,240,0), 1, cv2.CV_AA)

    # North
    uv = project_point(K, PROJ,
                       [ned[0] + 1.0, ned[1] + 0.0, ned[2] - 0.03])
    if uv != None:
        draw_label(frame, 'N', uv, font, 1, 2, vert='above')
    # South
    uv = project_point(K, PROJ,
                       [ned[0] - 1.0, ned[1] + 0.0, ned[2] - 0.03])
    if uv != None:
        draw_label(frame, 'S', uv, font, 1, 2, vert='above')
    # East
    uv = project_point(K, PROJ,
                       [ned[0] + 0.0, ned[1] + 1.0, ned[2] - 0.03])
    if uv != None:
        draw_label(frame, 'E', uv, font, 1, 2, vert='above')
    # West
    uv = project_point(K, PROJ,
                       [ned[0] + 0.0, ned[1] - 1.0, ned[2] - 0.03])
    if uv != None:
        draw_label(frame, 'W', uv, font, 1, 2, vert='above')

def draw_astro(K, PROJ, ned, frame):
    lat_deg = float(flight_gps_lat(time))
    lon_deg = float(flight_gps_lon(time))
    alt_m = float(flight_gps_alt(time))
    timestamp = float(flight_gps_unixtime(time))
    sun_ned, moon_ned = compute_sun_moon_ned(lon_deg, lat_deg, alt_m,
                                             timestamp)
    if sun_ned == None or moon_ned == None:
        return

    # Sun
    draw_labeled_point(K, PROJ, frame,
                       [ned[0] + sun_ned[0], ned[1] + sun_ned[1],
                        ned[2] + sun_ned[2]],
                       'Sun')
    # shadow (if sun above horizon)
    if sun_ned[2] < 0.0:
        draw_labeled_point(K, PROJ, frame,
                           [ned[0] - sun_ned[0], ned[1] - sun_ned[1],
                            ned[2] - sun_ned[2]],
                           'shadow', scale=0.7)
    # Moon
    draw_labeled_point(K, PROJ, frame,
                       [ned[0] + moon_ned[0], ned[1] + moon_ned[1],
                        ned[2] + moon_ned[2]],
                       'Moon')

def draw_airports(K, PROJ, frame):
    kmsp = [ 44.882000, -93.221802, 256 ]
    draw_lla_point(K, PROJ, frame, ned, kmsp, 'KMSP')
    ksgs = [ 44.857101, -93.032898, 250 ]
    draw_lla_point(K, PROJ, frame, ned, ksgs, 'KSGS')
    kstp = [ 44.934502, -93.059998, 215 ]
    draw_lla_point(K, PROJ, frame, ned, kstp, 'KSTP')
    my52 = [ 44.718601, -93.044098, 281 ]
    draw_lla_point(K, PROJ, frame, ned, my52, 'MY52')
    kfcm = [ 44.827202, -93.457100, 276 ]
    draw_lla_point(K, PROJ, frame, ned, kfcm, 'KFCM')
    kane = [ 45.145000, -93.211403, 278 ]
    draw_lla_point(K, PROJ, frame, ned, kane, 'KANE')
    klvn = [ 44.627899, -93.228104, 293 ]
    draw_lla_point(K, PROJ, frame, ned, klvn, 'KLVN')
    kmic = [ 45.062000, -93.353897, 265 ]
    draw_lla_point(K, PROJ, frame, ned, kmic, 'KMIC')
    mn45 = [ 44.566101, -93.132202, 290 ]
    draw_lla_point(K, PROJ, frame, ned, mn45, 'MN45')
    mn58 = [ 44.697701, -92.864098, 250 ]
    draw_lla_point(K, PROJ, frame, ned, mn58, 'MN58')
    mn18 = [ 45.187199, -93.130501, 276 ]
    draw_lla_point(K, PROJ, frame, ned, mn18, 'MN18')

def draw_nose(K, PROJ, ned, frame, body2ned):
    vec = transformations.quaternion_transform(body2ned, [1.0, 0.0, 0.0])
    uv = project_point(K, PROJ,
                       [ned[0] + vec[0], ned[1] + vec[1], ned[2]+ vec[2]])
    if uv != None:
        cv2.circle(frame, uv, 5, (0,240,0), 1, cv2.CV_AA)
        cv2.circle(frame, uv, 10, (0,240,0), 1, cv2.CV_AA)

    
vel_filt = [0.0, 0.0, 0.0]
def draw_velocity_vector(K, PROJ, ned, frame, vel):
    tf = 0.05
    for i in range(3):
        vel_filt[i] = (1.0 - tf) * vel_filt[i] + tf * vel[i]
        
    uv = project_point(K, PROJ,
                       [ned[0] + vel_filt[0], ned[1] + vel_filt[1],
                        ned[2]+ vel_filt[2]])
    if uv != None:
        cv2.circle(frame, uv, 5, (0,240,0), 1, cv2.CV_AA)

def draw_speed_tape(K, PROJ, ned, frame, airspeed, ap_speed):
    color = (0,240,0)
    size = 1
    pad = 5
    h, w, d = frame.shape
    # reference point
    cy = int(h * 0.5)
    cx = int(w * 0.2)
    # current airspeed
    label = "%.0f" % airspeed
    lsize = cv2.getTextSize(label, font, 0.7, 1)
    xsize = lsize[0][0] + pad
    ysize = lsize[0][1] + pad
    uv = ( int(cx + ysize*0.7), cy + lsize[0][1] / 2)
    cv2.putText(frame, label, uv, font, 0.7, (0,255,0), 1, cv2.CV_AA)
    uv1 = (cx, cy)
    uv2 = (cx + int(ysize*0.7),         cy - ysize / 2 )
    uv3 = (cx + int(ysize*0.7) + xsize, cy - ysize / 2 )
    uv4 = (cx + int(ysize*0.7) + xsize, cy + ysize / 2 )
    uv5 = (cx + int(ysize*0.7),         cy + ysize / 2 )
    cv2.line(frame, uv1, uv2, color, size, cv2.CV_AA)
    cv2.line(frame, uv2, uv3, color, size, cv2.CV_AA)
    cv2.line(frame, uv3, uv4, color, size, cv2.CV_AA)
    cv2.line(frame, uv4, uv5, color, size, cv2.CV_AA)
    cv2.line(frame, uv5, uv1, color, size, cv2.CV_AA)
        
if args.movie:
    # Mobius 1080p
    # K = np.array( [[1362.1,    0.0, 980.8],
    #                [   0.0, 1272.8, 601.3],
    #                [   0.0,    0.0,   1.0]] )
    # dist = [-0.36207197, 0.14627927, -0.00674558, 0.0008926, -0.02635695]

    # RunCamHD2 1920x1080
    K = np.array( [[ 971.96149426,   0.        , 957.46750602],
                   [   0.        , 971.67133264, 516.50578382],
                   [   0.        ,   0.        ,   1.        ]] )
    dist = [-0.26910665, 0.10580125, 0.00048417, 0.00000925, -0.02321387]

    # Runcamhd2 1920x1440
    # K = np.array( [[ 1296.11187055,     0.        ,   955.43024994],
    #                [    0.        ,  1296.01457451,   691.47053988],
    #                [    0.        ,     0.        ,     1.        ]] )
    # dist = [-0.28250371, 0.14064665, 0.00061846, 0.00014488, -0.05106045]
    
    K = K * args.scale
    K[2,2] = 1.0

    font = cv2.FONT_HERSHEY_SIMPLEX

    # these are fixed tranforms between ned and camera reference systems
    proj2ned = np.array( [[0, 0, 1], [1, 0, 0], [0, 1, 0]],
                         dtype=float )
    ned2proj = np.linalg.inv(proj2ned)

    #cam_ypr = [-3.0, -12.0, -3.0] # yaw, pitch, roll
    #ref = [44.7260320000, -93.0771072000, 0]
    ref = [ flight_gps[0][1], flight_gps[0][2], 0.0 ]
    print 'ned ref:', ref

    # overlay hud
    print "Opening ", args.movie
    try:
        capture = cv2.VideoCapture(args.movie)
    except:
        print "error opening video"

    capture.read()
    counter += 1
    print "ok reading first frame"

    fps = capture.get(cv2.cv.CV_CAP_PROP_FPS)
    print "fps = %.2f" % fps
    fourcc = int(capture.get(cv2.cv.CV_CAP_PROP_FOURCC))
    w = int(capture.get(cv2.cv.CV_CAP_PROP_FRAME_WIDTH) * args.scale )
    h = int(capture.get(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT) * args.scale )

    #outfourcc = cv2.cv.CV_FOURCC('M', 'J', 'P', 'G')
    #outfourcc = cv2.cv.CV_FOURCC('H', '2', '6', '4')
    #outfourcc = cv2.cv.CV_FOURCC('X', '2', '6', '4')
    #outfourcc = cv2.cv.CV_FOURCC('X', 'V', 'I', 'D')
    outfourcc = cv2.cv.CV_FOURCC('M', 'P', '4', 'V')
    print outfourcc, fps, w, h
    output = cv2.VideoWriter(tmp_movie, outfourcc, fps, (w, h), isColor=True)

    last_time = 0.0

    while True:
        ret, frame = capture.read()
        if not ret:
            # no frame
            stop_count += 1
            print "no more frames:", stop_count
            if stop_count > args.stop_count:
                break
        else:
            stop_count = 0
            
        if frame == None:
            print "Skipping bad frame ..."
            continue
        time = float(counter) / fps + time_shift
        print "frame: ", counter, time
        counter += 1
        vn = flight_filter_vn(time)
        ve = flight_filter_ve(time)
        vd = flight_filter_vd(time)
        #yaw_rad = flight_filter_yaw(time)*d2r 
        yaw_x = flight_filter_yaw_x(time)
        yaw_y = flight_filter_yaw_y(time)
        yaw_rad = math.atan2(yaw_y, yaw_x)
        pitch_rad = flight_filter_pitch(time)*d2r
        roll_rad = flight_filter_roll(time)*d2r
        lat_deg = float(flight_gps_lat(time))
        lon_deg = float(flight_gps_lon(time))
        altitude = float(flight_gps_alt(time))
        airspeed = float(flight_air_speed(time))
        #ap_hdg = float(flight_ap_hdg(time))
        ap_hdg_x = float(flight_ap_hdg_x(time))
        ap_hdg_y = float(flight_ap_hdg_y(time))
        ap_hdg = math.atan2(ap_hdg_y, ap_hdg_x)*r2d
        ap_roll = float(flight_ap_roll(time))
        ap_pitch = float(flight_ap_pitch(time))
        ap_speed = float(flight_ap_pitch(time))
        auto = float(flight_pilot_auto(time))

        body2cam = transformations.quaternion_from_euler( cam_yaw * d2r,
                                                          cam_pitch * d2r,
                                                          cam_roll * d2r,
                                                          'rzyx')

        #print 'att:', [yaw_rad, pitch_rad, roll_rad]
        ned2body = transformations.quaternion_from_euler(yaw_rad,
                                                         pitch_rad,
                                                         roll_rad,
                                                         'rzyx')
        body2ned = transformations.quaternion_inverse(ned2body)
        
        #print 'ned2body(q):', ned2body
        ned2cam_q = transformations.quaternion_multiply(ned2body, body2cam)
        ned2cam = np.matrix(transformations.quaternion_matrix(np.array(ned2cam_q))[:3,:3]).T
        #print 'ned2cam:', ned2cam
        R = ned2proj.dot( ned2cam )
        rvec, jac = cv2.Rodrigues(R)
        ned = navpy.lla2ned( lat_deg, lon_deg, altitude,
                             ref[0], ref[1], ref[2] )
        #print 'ned:', ned
        tvec = -np.matrix(R) * np.matrix(ned).T
        R, jac = cv2.Rodrigues(rvec)
        # is this R the same as the earlier R?
        PROJ = np.concatenate((R, tvec), axis=1)
        #print 'PROJ:', PROJ
        #print lat_deg, lon_deg, altitude, ref[0], ref[1], ref[2]
        #print ned

        method = cv2.INTER_AREA
        #method = cv2.INTER_LANCZOS4
        frame_scale = cv2.resize(frame, (0,0), fx=args.scale, fy=args.scale,
                                 interpolation=method)
        frame_undist = cv2.undistort(frame_scale, K, np.array(dist))

        cv2.putText(frame_undist, 'alt = %.0f' % altitude, (100, 100), font, 1, (0,255,0), 2,cv2.CV_AA)
        # cv2.putText(frame_undist, 'kts = %.0f' % airspeed, (100, 150), font, 1, (0,255,0), 2,cv2.CV_AA)

        draw_horizon(K, PROJ, ned, frame_undist)
        draw_compass_points(K, PROJ, ned, frame_undist)
        draw_pitch_ladder(K, PROJ, ned, frame_undist, yaw_rad)
        draw_astro(K, PROJ, ned, frame_undist)
        draw_airports(K, PROJ, frame_undist)
        draw_velocity_vector(K, PROJ, ned, frame_undist, [vn, ve, vd])
        draw_speed_tape(K, PROJ, ned, frame_undist, airspeed, ap_speed)
        if auto < 0:
            draw_nose(K, PROJ, ned, frame_undist, body2ned)
        else:
            draw_vbars(K, PROJ, ned, frame_undist, yaw_rad, pitch_rad,
                       ap_roll, ap_pitch)
            draw_heading_bug(K, PROJ, ned, frame_undist, ap_hdg)
            draw_bird(K, PROJ, ned, frame_undist, yaw_rad, pitch_rad, roll_rad)
            draw_course(K, PROJ, ned, frame_undist, vn, ve)
        
        cv2.imshow('hud', frame_undist)
        output.write(frame_undist)
        
        key = cv2.waitKey(5) & 0xFF
        if key == 27:
            break
        elif key == ord('y'):
            cam_yaw += 0.5
            config.setFloat('cam_yaw_deg', cam_yaw)
            props_json.save(movie_config, config)
        elif key == ord('Y'):
            cam_yaw -= 0.5
            config.setFloat('cam_yaw_deg', cam_yaw)
            props_json.save(movie_config, config)
        elif key == ord('p'):
            cam_pitch += 0.5
            config.setFloat('cam_pitch_deg', cam_pitch)
            props_json.save(movie_config, config)
        elif key == ord('P'):
            cam_pitch -= 0.5
            config.setFloat('cam_pitch_deg', cam_pitch)
            props_json.save(movie_config, config)
        elif key == ord('r'):
            cam_roll -= 0.5
            config.setFloat('cam_roll_deg', cam_roll)
            props_json.save(movie_config, config)
        elif key == ord('R'):
            cam_roll += 0.5
            config.setFloat('cam_roll_deg', cam_roll)
            props_json.save(movie_config, config)

output.release()
cv2.destroyAllWindows()

# now run ffmpeg as an external command to combine original audio
# track with new overlay video

# ex: ffmpeg -i opencv.avi -i orig.mov -c copy -map 0:v -map 1:a final.avi

from subprocess import call
call(["ffmpeg", "-i", tmp_movie, "-i", args.movie, "-c", "copy", "-map", "0:v", "-map", "1:a", output_movie])

if args.plot:
    # plot the data ...
    plt.figure(1)
    plt.ylabel('roll rate (deg per sec)')
    plt.xlabel('flight time (sec)')
    plt.plot(movie[:,0] + time_shift, movie[:,2]*r2d, label='estimate from flight movie')
    if args.apm_log:
        plt.plot(flight_imu[:,0], flight_imu[:,3]*r2d, label='flight data log')
    else:
        plt.plot(flight_imu[:,0], flight_imu[:,1]*r2d, label='flight data log')
    #plt.plot(movie_interp[:,1])
    #plt.plot(flight_interp[:,1])
    plt.legend()

    plt.figure(2)
    plt.plot(ycorr)

    plt.figure(3)
    plt.ylabel('pitch rate (deg per sec)')
    plt.xlabel('flight time (sec)')
    plt.plot(movie[:,0] + time_shift, (movie[:,3]/qratio)*r2d, label='estimate from flight movie')
    plt.plot(flight_imu[:,0], flight_imu[:,2]*r2d, label='flight data log')
    #plt.plot(movie_interp[:,1])
    #plt.plot(flight_interp[:,1])
    plt.legend()

    plt.figure(4)
    plt.ylabel('yaw rate (deg per sec)')
    plt.xlabel('flight time (sec)')
    plt.plot(movie[:,0] + time_shift, (movie[:,4]/rratio)*r2d, label='estimate from flight movie')
    plt.plot(flight_imu[:,0], flight_imu[:,3]*r2d, label='flight data log')
    #plt.plot(movie_interp[:,1])
    #plt.plot(flight_interp[:,1])
    plt.legend()

    plt.show()
