# Slot Machine
![Tests](https://github.com/emfcamp/slotmachine/workflows/Tests/badge.svg?event=push)

A conference schedule optimizer using mixed integer linear programming.
This is used to generate the schedule for [Electromagnetic Field](https://www.emfcamp.org) events.

## Requirements

This uses [OR-Tools](https://github.com/google/or-tools), which should be automatically installed from pypy.

## Acknowledgements

The concept and code for the original [CBC](https://projects.coin-or.org/Cbc)-based version of this library is from [David MacIver](http://www.drmaciver.com/). 

For more information on this approach, see David's talk [Easy solutions to hard
problems](https://www.youtube.com/watch?v=OkusHEBOhmQ) from PyCon UK 2016.

A similar library with a slightly different approach is [conference-scheduler](http://conference-scheduler.readthedocs.io/en/latest/).
