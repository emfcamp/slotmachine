# Slot Machine
[![Build Status](https://travis-ci.org/emfcamp/slotmachine.svg?branch=master)](https://travis-ci.org/emfcamp/slotmachine)
A conference schedule optimizer using mixed integer linear programming.
This is used to generate the schedule for [Electromagnetic Field](https://www.emfcamp.org) events.

## Requirements

You'll need the GLPK solver installed to use this library. `apt-get install glpk-utils` or `brew install glpk`.

## Acknowledgements

The original concept and code for this library is from [David MacIver](http://www.drmaciver.com/).
For more information on this approach, see David's talk
[Easy solutions to hard problems](https://www.youtube.com/watch?v=OkusHEBOhmQ) from PyCon UK 2016.

A similar library with a slightly different approach is [conference-scheduler](http://conference-scheduler.readthedocs.io/en/latest/).
