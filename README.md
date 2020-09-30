# Slot Machine
![Tests](https://github.com/emfcamp/slotmachine/workflows/Tests/badge.svg?event=push)

A conference schedule optimizer using mixed-integer linear programming.
This is used to generate the schedule for [Electromagnetic Field](https://www.emfcamp.org) events.

## Requirements

You'll need the [COIN-OR](https://www.coin-or.org/) [CBC](https://projects.coin-or.org/Cbc) solver installed to use this library.
`apt-get install coinor-cbc` or `brew tap coin-or-tools/coinor && brew install cbc`.

## Acknowledgments

The original concept and code for this library are from [David MacIver](http://www.drmaciver.com/).
For more information on this approach, see David's talk
[Easy solutions to hard problems](https://www.youtube.com/watch?v=OkusHEBOhmQ) from PyCon UK 2016.

A similar library with a slightly different approach is [conference-scheduler](http://conference-scheduler.readthedocs.io/en/latest/).
