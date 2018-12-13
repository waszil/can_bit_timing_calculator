# CAN_BitTimingCalculation
Bit level timing calculator for CAN/CANFD

## F_in:
given input clock frequency of the CAN protocol controller
##Prescaler:
scales down the input clock for the internal time base:

## TimeQuantum = 1/F_in * Prescaler
e.g.:
F_in        = 80 MHz
Prescaler   = 8
TimeQuantum = 1/80000000*8 = 0.0000001 s = 100 ns

## Bit Time:
Each bit is divided into 4 segments:

<---------------- T_bit ------------------->
--------------------------------------------
|  SYNC   |  PROP   |  PHASE1   !  PHASE2  |
--------------------------------------------
          <-------TSEG1---------><--TSEG2-->
                              <-SJW->

SYNC:   Synchronization segment
            always 1 TimeQuantum long by the CAN standard
PROP:   Propagation segment
PHASE1: Phase segment1
PHASE2: Phase segment2
!:      Sample point: always at the end of Phase segment 1. Can be expressed as a
            position in the BitTime in percentage.
TSEG1:  Time segment 1: usually this can be configured in a CAN controller
            minimum 1 TimeQuantum long
TSEG2:  Time segment 2: usually this can be configured in a CAN controller
            minimum 1 TimeQuantum long
SJW:    (Re)Synchronization Jump Width: The controller can lengthen TSEG1 or
        shorten TSEG2 by this value at resynchronization.

## TimeQuanta/BitTime:
The number of TimeQuanta in a bit time:
    TQ/BT = SYNC + TSEG1 + TSEG2 = 1 + TSEG1 + TSEG2

## SamplePoint:
Position of the sample point in the bit time in percentage:
    SP = (SYNC + TSEG1) / TQ/BT * 100 %

## BaudRate:
Comes from the TimeQuantum, and the TQ/BT
                     1
BaudRate = ---------------------
            TimeQuantum * TQ/BT

So with the wbove example and with TSEG1 = 15 and TSEG2 = 4:
    TQ/BT = 1 + 15 + 4 = 20
    BaudRate = 1 / (20 * 100ns) = 500000 = 500 kbps
    SamplePoint = (1 + 15) / 20 * 100% = 80%
