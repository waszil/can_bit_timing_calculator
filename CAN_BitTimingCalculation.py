# -*- coding: utf-8 -*-
# =============================================================================
# Target:   Python 3.5
# =============================================================================

"""
CAN BitTiming calculation

F_in:
    given input clock frequency of the CAN protocol controller
Prescaler:
    scales down the input clock for the internal time base:

TimeQuantum = 1/F_in * Prescaler
    e.g.:
        F_in        = 80 MHz
        Prescaler   = 8
        TimeQuantum = 1/80000000*8 = 0.0000001 s = 100 ns

Bit Time:
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

TimeQuanta/BitTime:
    The number of TimeQuanta in a bit time:
        TQ/BT = SYNC + TSEG1 + TSEG2 = 1 + TSEG1 + TSEG2

SamplePoint:
    Position of the sample point in the bit time in percentage:
        SP = (SYNC + TSEG1) / TQ/BT * 100 %

BaudRate:
    Comes from the TimeQuantum, and the TQ/BT
                         1
    BaudRate = ---------------------
                TimeQuantum * TQ/BT

So with the wbove example and with TSEG1 = 15 and TSEG2 = 4:
    TQ/BT = 1 + 15 + 4 = 20
    BaudRate = 1 / (20 * 100ns) = 500000 = 500 kbps
    SamplePoint = (1 + 15) / 20 * 100% = 80%

"""

from dataclasses import dataclass
from typing import List, Tuple
import sys
from enum import Enum, unique
from PyQt5 import QtWidgets, QtCore, QtGui


# list of baud rates to calculate for
CanBaudRatesKbps = [250, 500, 800, 1000]
CanFDBaudRatesKbps = CanBaudRatesKbps[:] + [2000, 4000, 6000]
# Synchronization segment is 1 time quantum by standard
SyncSegment = 1
# Minimal sample point to calculate with
MinimalSamplePoint = 70     # [%]


def _range(r: Tuple[int, int]) -> List[int]:
    """
    Helper: gives a closed interval
    :param r: tuple: (min_val, max_val)
    :return: [min_val, min_val+1, ..., max_val-1, max_val]
    """
    return list(range(r[0], r[1] + 1))


@unique
class CanPhase(Enum):
    # Arbitration phase (ID, DLC, etc.)
    Arbitration = 0
    # Data phase: Payload. For CAN-FD frames, the second Baudrate is activated here.
    Data = 1


@dataclass
class BitTiming:
    """
    Calculated bit timing parameters
    """
    # sample point location inside the bit time in [%]
    SamplePoint: float
    # length of a time quantum in [s]
    TimeQuantumSec: float
    # number of time quanta per bit time
    TimeQuantaPerBitTime: int
    # time segment 1 (propagation segment + phase segment 1)
    TS1: int
    # time segment 2 (phase segment 2)
    TS2: int
    Prescaler: int
    # actual SJW
    SyncJumpWidthActual: int


@dataclass
class TimingInfo:
    # Parameters below refer to the following phase
    Phase: CanPhase
    # Ranges for parameters that the device can handle
    TimeSegment1_range: List[int]
    TimeSegment2_range: List[int]
    SyncJumpWidth_range: List[int]
    PreScaler_range: List[int]


@dataclass
class CanDevice:
    name: str
    comment: str
    # input clock frequency in [Hz]
    F_in: int
    # maximal baud rate supported by the device
    MaxBaudRate: int
    # timing infos for device
    TimingInfoList: List[TimingInfo]
    # maximal FD baudrate supported by the device
    MaxFDBaudRate: int = 0


# device definitions
CanDeviceList: List[CanDevice] = [
    CanDevice(
        name="SJA1000",
        comment="SJA1000 compatible CAN IP from OpenCores",
        F_in=24000000,
        MaxBaudRate=1000,
        TimingInfoList=[
            TimingInfo(
                Phase=CanPhase.Arbitration,
                TimeSegment1_range=_range((1, 16)),
                TimeSegment2_range=_range((1, 8)),
                SyncJumpWidth_range=_range((1, 4)),
                PreScaler_range=_range((1, 64)),
            )
        ]
    ),
    CanDevice(
        name="XCANFD",
        comment="Xilinx CANFD IP",
        F_in=80000000,
        MaxBaudRate=1000,
        TimingInfoList=[
            TimingInfo(
                Phase=CanPhase.Arbitration,
                TimeSegment1_range=_range((1, 64)),
                TimeSegment2_range=_range((1, 32)),
                SyncJumpWidth_range=_range((1, 16)),
                PreScaler_range=_range((1, 256)),
            ),
            TimingInfo(
                Phase=CanPhase.Data,
                TimeSegment1_range=_range((1, 16)),
                TimeSegment2_range=_range((1, 8)),
                SyncJumpWidth_range=_range((1, 4)),
                PreScaler_range=_range((1, 256)),
            )
        ],
        MaxFDBaudRate=2000
    )
]


def calculateBitTimings(F_in: int,
                        baudRateBps: int,
                        target_sjw: int,
                        timingInfo: TimingInfo) -> List[BitTiming]:
    """
    Calculates bit timing parameters
    :param F_in: device input clock (that gets divided by the prescaler)
    :param baudRateBps: target baud rate to calculate for
    :param target_sjw: target SJW to aim
    :param timingInfo: device timing info to calculate with
    :return: list of bit timings
    """
    bitTimingList: List[BitTiming] = []
    for TS1 in timingInfo.TimeSegment1_range:
        for TS2 in timingInfo.TimeSegment2_range:
            TimeQuantaPerBitTime = SyncSegment + TS1 + TS2
            prescaler = F_in / (baudRateBps * TimeQuantaPerBitTime)
            if prescaler not in timingInfo.PreScaler_range:
                continue
            prescaler = int(prescaler)
            TimeQuantumSec = (1 / F_in) * prescaler
            SamplePoint = (SyncSegment + TS1) / TimeQuantaPerBitTime * 100
            if SamplePoint < MinimalSamplePoint:
                continue
            # limit SJW by ts1, ts2, and max_sjw
            act_sjw = min(target_sjw, TS1, TS2, timingInfo.SyncJumpWidth_range[-1])
            bt = BitTiming(SamplePoint, TimeQuantumSec, TimeQuantaPerBitTime, TS1, TS2, prescaler, act_sjw)
            bitTimingList.append(bt)
    return bitTimingList


class Canvas(QtWidgets.QGraphicsView):
    """
    Visualization canvas
    """
    def __init__(self):
        super().__init__()
        self.scene = QtWidgets.QGraphicsScene()
        self.setScene(self.scene)
        self.zoom = 0
        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)

    def draw(self, bitTiming: BitTiming):
        self.scene.clear()
        pen = QtGui.QPen(QtCore.Qt.black)
        synBrush = QtGui.QBrush(QtCore.Qt.gray, QtCore.Qt.SolidPattern)
        ts1Brush = QtGui.QBrush(QtCore.Qt.cyan, QtCore.Qt.SolidPattern)
        ts2Brush = QtGui.QBrush(QtCore.Qt.magenta, QtCore.Qt.SolidPattern)
        _w = self.width() * 0.9
        w = _w / bitTiming.TimeQuantaPerBitTime
        h = 20
        size = QtCore.QSizeF(w, h)
        x = 0
        font = QtGui.QFont('arial', 8)
        self.scene.addRect(QtCore.QRectF(x, 0, w, h), pen, synBrush)
        self.scene.addText('SYN', font).setPos(x + w/2 - 5, -2*h)
        x += w
        self.scene.addText('TSEG1', font).setPos(x + bitTiming.TS1*w/2 - 5, -2*h)
        for tq in range(bitTiming.TS1):
            pos = QtCore.QPointF(x, 0)
            x += w
            rect = QtCore.QRectF(pos, size)
            self.scene.addRect(rect, pen, ts1Brush)
        self.scene.addText('TSEG2', font).setPos(x + bitTiming.TS2 * w / 2 - 5, -2*h)
        self.scene.addLine(x, 0, x, h*2, pen)
        self.scene.addText('Sampling point', font).setPos(x - 25, 2*h)
        for tq in range(bitTiming.TS2):
            pos = QtCore.QPointF(x, 0)
            x += w
            rect = QtCore.QRectF(pos, size)
            self.scene.addRect(rect, pen, ts2Brush)

    def wheelEvent(self, event: QtGui.QWheelEvent):
        adj = 1/(event.angleDelta().y() / 120) * 0.1
        self.scale(1 + adj, 1 + adj)


class MainWindow(QtWidgets.QWidget):
    """
    Main GUI window
    """
    def __init__(self):
        super().__init__()
        self.currentBaudRateBps: int = None
        self.currentPhase: CanPhase = None
        self.initUI()

    def initUI(self):
        self.setGeometry(300, 300, 300, 220)
        self.setWindowTitle('CAN Bit Timing Wizard')

        self.mainLay = QtWidgets.QVBoxLayout(self)
        self.labelLay = QtWidgets.QHBoxLayout(self)
        self.listLay = QtWidgets.QHBoxLayout(self)
        self.btLay = QtWidgets.QVBoxLayout(self)
        self.drawLay = QtWidgets.QHBoxLayout(self)
        self.setLayout(self.mainLay)

        self.canvas = Canvas()

        self.deviceLay = QtWidgets.QVBoxLayout(self)
        self.deviceList = QtWidgets.QListWidget()
        self.deviceLay.addWidget(QtWidgets.QLabel('Devices'))
        self.deviceLay.addWidget(self.deviceList)
        self.f_in_MHz_value = QtWidgets.QSpinBox()
        self.f_in_MHz_value.setRange(1, 1000)
        finLay = QtWidgets.QHBoxLayout(self)
        finLay.addWidget(QtWidgets.QLabel('F_in [MHz]:'), stretch=1)
        finLay.addWidget(self.f_in_MHz_value, stretch=1)
        finLay.addStretch(stretch=2)
        self.sjw_value = QtWidgets.QSpinBox()
        self.sjw_value.setRange(0, 128)
        sjwLay = QtWidgets.QHBoxLayout(self)
        sjwLay.addWidget(QtWidgets.QLabel('Target SJW [time quanta]:'), stretch=1)
        sjwLay.addWidget(self.sjw_value, stretch=1)
        sjwLay.addStretch(stretch=2)
        self.deviceLay.addLayout(finLay)
        self.deviceLay.addLayout(sjwLay)

        self.arbitrationBaudRateLay = QtWidgets.QVBoxLayout(self)
        self.arbitrationBaudRateList = QtWidgets.QListWidget()
        self.arbitrationBaudRateLay.addWidget(QtWidgets.QLabel('Arbitration Phase Baud rates [kbps]'))
        self.arbitrationBaudRateLay.addWidget(self.arbitrationBaudRateList)

        self.dataBaudRateLay = QtWidgets.QVBoxLayout(self)
        self.dataBaudRateList = QtWidgets.QListWidget()
        self.dataBaudRateLay.addWidget(QtWidgets.QLabel('Data Phase Baud rates [kbps]'))
        self.dataBaudRateLay.addWidget(self.dataBaudRateList)

        self.bitTimingTable = QtWidgets.QTableWidget()
        labels = (
            'Sample point [%]',
            'Time quantum [ns]',
            'TQ/BitTime',
            'TimeSegment1',
            'TimeSegment2',
            'Prescaler',
            'SJW actual'
        )
        self.bitTimingTable.setColumnCount(len(labels))
        self.bitTimingTable.setHorizontalHeaderLabels(labels)
        self.bitTimingTable.verticalHeader().setVisible(False)
        self.bitTimingTable.clearContents()
        self.bitTimingTable.setSelectionBehavior(QtWidgets.QTableWidget.SelectRows)
        header = self.bitTimingTable.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        self.BT_PARAM_LABEL = 'Bit Timing parameters'
        self.btParamLabel = QtWidgets.QLabel(self.BT_PARAM_LABEL)
        self.btLay.addWidget(self.btParamLabel)

        self.listLay.addLayout(self.deviceLay, stretch=2)
        self.listLay.addLayout(self.arbitrationBaudRateLay, stretch=1)
        self.listLay.addLayout(self.dataBaudRateLay, stretch=1)

        self.btLay.addWidget(self.bitTimingTable)
        self.drawLay.addWidget(self.canvas)

        self.mainLay.addLayout(self.labelLay, stretch=0)
        self.mainLay.addLayout(self.listLay, stretch=1)
        self.mainLay.addLayout(self.btLay, stretch=3)
        self.mainLay.addLayout(self.drawLay, stretch=1)

        for device in CanDeviceList:
            item = QtWidgets.QListWidgetItem(f'{device.name} ({device.comment})')
            item.setData(QtCore.Qt.UserRole, device)
            self.deviceList.addItem(item)

        self.deviceList.currentItemChanged.connect(self.deviceChanged)

        self.arbitrationBaudRateList.itemClicked.connect(self.baudRateListClicked)
        self.arbitrationBaudRateList.currentItemChanged.connect(self.baudRateChanged)
        self.dataBaudRateList.itemClicked.connect(self.baudRateListClicked)
        self.dataBaudRateList.currentItemChanged.connect(self.baudRateChanged)

        self.bitTimingTable.currentCellChanged.connect(self.updateVisualization)
        self.f_in_MHz_value.valueChanged.connect(self.finChanged)
        self.sjw_value.valueChanged.connect(self.sjwChanged)

        self.deviceList.setCurrentRow(0)

        self.setMinimumSize(800, 600)
        self.showMaximized()

    @QtCore.pyqtSlot(QtWidgets.QListWidgetItem)
    def baudRateListClicked(self, item: QtWidgets.QListWidgetItem):
        if item is None:
            return
        phase: CanPhase = None
        baudRateBps: int = None
        phase, baudRateBps = item.data(QtCore.Qt.UserRole)
        doCalc = False
        if phase != self.currentPhase:
            doCalc = True
        self.currentPhase = phase
        self.currentBaudRateBps = baudRateBps
        self.btParamLabel.setText(f'{self.BT_PARAM_LABEL} for {self.currentPhase.name} phase')
        if doCalc:
            self.calculate()

    @QtCore.pyqtSlot(int)
    def finChanged(self, value: int):
        currDevItem = self.deviceList.currentItem()
        if currDevItem is None:
            return
        currDev: CanDevice = None
        currDev = currDevItem.data(QtCore.Qt.UserRole)
        if value*1e6 != currDev.F_in:
            self.f_in_MHz_value.setStyleSheet('background-color: #aef;')
        else:
            self.f_in_MHz_value.setStyleSheet('background-color: white;')
        self.calculate()

    @QtCore.pyqtSlot(int)
    def sjwChanged(self, value: int):
        self.calculate()

    @QtCore.pyqtSlot(int)
    def updateVisualization(self, row):
        if row >= 0:
            item = self.bitTimingTable.item(row, 0)
            bitTiming = item.data(QtCore.Qt.UserRole)
            self.canvas.draw(bitTiming)

    @QtCore.pyqtSlot(QtWidgets.QListWidgetItem)
    def deviceChanged(self, item: QtWidgets.QListWidgetItem):
        if item is None:
            return
        self.currentBaudRateBps = None
        self.currentPhase = None
        self.btParamLabel.setText(self.BT_PARAM_LABEL)
        self.arbitrationBaudRateList.clear()
        self.dataBaudRateList.clear()
        self.bitTimingTable.clearContents()
        self.bitTimingTable.setRowCount(0)
        self.canvas.scene.clear()
        device: CanDevice = item.data(QtCore.Qt.UserRole)
        self.f_in_MHz_value.setValue(int(device.F_in / 1e6))
        self.f_in_MHz_value.setStyleSheet('background-color: white;')
        for timingInfo in device.TimingInfoList:
            if timingInfo.Phase is CanPhase.Arbitration:
                brList = [br*1000 for br in CanBaudRatesKbps if br <= device.MaxBaudRate]
                listWidget = self.arbitrationBaudRateList
            elif timingInfo.Phase is CanPhase.Data:
                brList = [br*1000 for br in CanFDBaudRatesKbps if br <= device.MaxFDBaudRate]
                listWidget = self.dataBaudRateList
            else:
                raise TypeError
            for baudRateBps in brList:
                item = QtWidgets.QListWidgetItem(f'{baudRateBps/1000:.1f}')
                item.setData(QtCore.Qt.UserRole, (timingInfo.Phase, baudRateBps))
                listWidget.addItem(item)

    @QtCore.pyqtSlot(QtWidgets.QListWidgetItem)
    def baudRateChanged(self, item: QtWidgets.QListWidgetItem):
        if item is None:
            return
        phase: CanPhase = None
        baudRateBps: int = None
        phase, baudRateBps = item.data(QtCore.Qt.UserRole)
        self.currentPhase = phase
        self.currentBaudRateBps = baudRateBps
        self.calculate()

    def calculate(self):
        if self.currentPhase is None or self.currentBaudRateBps is None:
            return
        deviceItem = self.deviceList.currentItem()
        if deviceItem is None:
            return
        device: CanDevice = deviceItem.data(QtCore.Qt.UserRole)

        self.bitTimingTable.clearContents()
        self.canvas.scene.clear()
        self.bitTimingTable.setRowCount(0)
        f_in = int(self.f_in_MHz_value.value() * 1e6)
        timingInfo = None
        for _timingInfo in device.TimingInfoList:
            if _timingInfo.Phase == self.currentPhase:
                timingInfo = _timingInfo
        if timingInfo is not None:
            bitTimingList = calculateBitTimings(F_in=f_in,
                                                baudRateBps=self.currentBaudRateBps,
                                                target_sjw=self.sjw_value.value(),
                                                timingInfo=timingInfo)
            for row, bitTiming in enumerate(bitTimingList):
                self.bitTimingTable.insertRow(row)
                item = QtWidgets.QTableWidgetItem(f'{bitTiming.SamplePoint:.1f}')
                item.setData(QtCore.Qt.UserRole, bitTiming)
                self.bitTimingTable.setItem(row, 0, item)
                self.bitTimingTable.setItem(row, 1, QtWidgets.QTableWidgetItem(f'{bitTiming.TimeQuantumSec*1e9:.3f}'))
                self.bitTimingTable.setItem(row, 2, QtWidgets.QTableWidgetItem(f'{bitTiming.TimeQuantaPerBitTime}'))
                self.bitTimingTable.setItem(row, 3, QtWidgets.QTableWidgetItem(f'{bitTiming.TS1}'))
                self.bitTimingTable.setItem(row, 4, QtWidgets.QTableWidgetItem(f'{bitTiming.TS2}'))
                self.bitTimingTable.setItem(row, 5, QtWidgets.QTableWidgetItem(f'{bitTiming.Prescaler}'))
                self.bitTimingTable.setItem(row, 6, QtWidgets.QTableWidgetItem(f'{bitTiming.SyncJumpWidthActual}'))


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    mainWindow = MainWindow()
    mainWindow.show()
    sys.exit(app.exec())
