#!/usr/bin/env python

from setuptools import setup, Extension

setup(name='lights',
      version='1.0',
      description='Python Light module for working with color LEDs',
      author='Kevron Rees',
      author_email='tripzero.kev@gmail.com',
      url='https://github.com/tripzero/python-lights',
      packages=["lights"],
      install_requires=["trollius"]
      )