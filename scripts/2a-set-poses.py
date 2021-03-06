#!/usr/bin/python3

import argparse
import os

from props import getNode

from lib import pose
from lib import project

# for all the images in the project image_dir, detect features using the
# specified method and parameters

parser = argparse.ArgumentParser(description='Set the aircraft poses from flight data.')
parser.add_argument('project', help='project directory')
parser.add_argument('--max-angle', type=float, default=25.0, help='max pitch or roll angle for image inclusion')

args = parser.parse_args()

proj = project.ProjectMgr(args.project)
print("Loading image info...")
proj.load_images_info()

# simplifying assumption
image_dir = args.project
    
pix4d_file = os.path.join(image_dir, 'pix4d.csv')
meta_file = os.path.join(image_dir, 'image-metadata.txt')
if os.path.exists(pix4d_file):
    pose.set_aircraft_poses(proj, pix4d_file, order='rpy',
                            max_angle=args.max_angle)
elif os.path.exists(meta_file):
    pose.set_aircraft_poses(proj, meta_file, order='ypr',
                            max_angle=args.max_angle)
else:
    print("Error: no pose file found in image directory:", image_dir)
    quit()

# compute the project's NED reference location (based on average of
# aircraft poses)
proj.compute_ned_reference_lla()
ned_node = getNode('/config/ned_reference', True)
print("NED reference location:")
ned_node.pretty_print("  ")

# set the camera poses (fixed offset from aircraft pose) Camera pose
# location is specfied in ned, so do this after computing the ned
# reference point for this project.
pose.compute_camera_poses(proj)

# save the poses
proj.save_images_info()

# save change to ned reference
proj.save()
    
