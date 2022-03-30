"""
CAN BitTiming calculation GUI.

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

import sys

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List
from PyQt5 import QtWidgets, QtCore, QtGui


# list of baud rates to calculate for
CanBaudRatesKbps = [250, 500, 800, 1000]
CanFDBaudRatesKbps = CanBaudRatesKbps[:] + [2000, 4000, 6000]


# Synchronization segment is 1 time quantum by standard
SyncSegment = 1
# Default sample point range to calculate for
DefaultSamplePointRange = (50, 100)     # [%]


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

    def __keys(self):
        """
        Attributes to be used in __eq__ and __hash__:
        These will be compared between two instances
        """
        return self.SamplePoint, self.SyncJumpWidthActual

    def __eq__(self, other):
        return self.__keys() == other.__keys()

    def __hash__(self):
        return hash(self.__keys())


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
    TimingInfos: Dict[CanPhase, TimingInfo]
    # maximal FD baudrate supported by the device
    MaxFDBaudRate: int = 0
    setter_offset_ts1: int = 0
    setter_offset_ts2: int = 0
    setter_offset_sjw: int = 0
    setter_offset_prescaler: int = 0

    def _get_timings(
            self,
            baud_rate_bps: float,
            phase=CanPhase.Arbitration,
            target_sjw=3,
            unique=True
    ):
        """Get timings for given baud rate"""
        timings = calculate_bit_timings(
            f_in=self.F_in,
            baud_rate_bps=baud_rate_bps,
            target_sjw=target_sjw,
            timing_info=self.TimingInfos[phase]
        )
        if unique:
            # filter out the same timings, based on the BitTiming class' selected
            # attributes defined in BitTiming.__keys(), by applying a set.
            return list(set(timings))
        else:
            return timings

    def get_timings(self, baud_rate_bps: float, target_sjw=3, unique=True):
        """Get all timings for given baud rate"""
        return self._get_timings(baud_rate_bps=baud_rate_bps, phase=CanPhase.Arbitration, target_sjw=target_sjw,
                                 unique=unique)

    def get_fd_timings(self, baud_rate_bps: int, target_sjw=3, unique=True):
        """Get all FD timings for given baud rate"""
        return self._get_timings(baud_rate_bps=baud_rate_bps, phase=CanPhase.Data, target_sjw=target_sjw,
                                 unique=unique)

    def get_timing(self, baud_rate_bps: int, sampling_point_target: float, search_range_percent=1, target_sjw=3):
        """Get timing for a given baud rate ad sampling point"""
        assert DefaultSamplePointRange[0] <= sampling_point_target <= DefaultSamplePointRange[1]
        timings = self.get_timings(baud_rate_bps=baud_rate_bps, target_sjw=target_sjw)
        return self._get_timing(timings, sampling_point_target, search_range_percent)

    def get_fd_timing(self, baud_rate_bps: int, sampling_point_target: float, search_range_percent=1, target_sjw=3):
        """Get FD timing for a given baud rate ad sampling point"""
        assert DefaultSamplePointRange[0] <= sampling_point_target <= DefaultSamplePointRange[1]
        timings = self.get_fd_timings(baud_rate_bps=baud_rate_bps, target_sjw=target_sjw)
        return self._get_timing(timings, sampling_point_target, search_range_percent)

    @staticmethod
    def _get_timing(timings, sampling_point_target: float, search_range_percent=1):
        _min = sampling_point_target - search_range_percent
        _max = sampling_point_target + search_range_percent
        return next((t for t in timings if _min < t.SamplePoint < _max), None)


def calculate_bit_timings(
        f_in: int,
        baud_rate_bps: float,
        target_sjw: int,
        timing_info: TimingInfo,
        sample_point_range=DefaultSamplePointRange
) -> List[BitTiming]:
    """
    Calculates bit timing parameters

    =======================================================================
    CAN BitTiming calculation background:

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
    =======================================================================

    :param f_in: device input clock (that gets divided by the prescaler)
    :param baud_rate_bps: target baud rate to calculate for
    :param target_sjw: target SJW to aim
    :param timing_info: device timing info to calculate with
    :param sample_point_range: range in percent to calculate for.

    :return: list of bit timings
    """
    bit_timing_list: List[BitTiming] = []
    for TS1 in timing_info.TimeSegment1_range:
        for TS2 in timing_info.TimeSegment2_range:
            time_quanta_per_bit_time = SyncSegment + TS1 + TS2
            prescaler = f_in / (baud_rate_bps * time_quanta_per_bit_time)
            # p * b * t  = f
            # b = f / (p * t)
            if prescaler not in timing_info.PreScaler_range:
                continue
            prescaler = int(prescaler)
            time_quantum_sec = (1 / f_in) * prescaler
            sample_point = (SyncSegment + TS1) / time_quanta_per_bit_time * 100
            if not sample_point_range[0] <= sample_point <= sample_point_range[1]:
                continue
            # limit SJW by ts1, ts2, and max_sjw
            act_sjw = min(target_sjw, TS1, TS2, timing_info.SyncJumpWidth_range[-1])
            bt = BitTiming(sample_point, time_quantum_sec, time_quanta_per_bit_time, TS1, TS2, prescaler, act_sjw)
            bit_timing_list.append(bt)
    # sort based on:
    #   primary key:    sample point, ascending
    #   secondary key:  prescaler, descending
    bit_timing_list.sort(key=lambda x: (x.SamplePoint, -x.Prescaler))
    return bit_timing_list


def closed_range(*r) -> List[int]:
    """
    Helper: gives a closed interval
    :param r: two integers: min_val, max_val
    :return: [min_val, min_val+1, ..., max_val-1, max_val]
    """
    assert len(r) == 2
    start, end = r
    return list(range(start, end + 1))


CANDeviceXCANFD = CanDevice(
    name="XCANFD",
    comment="Xilinx CANFD IP",
    F_in=36000000,
    MaxBaudRate=1000,
    TimingInfos={
        CanPhase.Arbitration:
        TimingInfo(
            Phase=CanPhase.Arbitration,
            TimeSegment1_range=closed_range(1, 0x100),
            TimeSegment2_range=closed_range(1, 0x80),
            SyncJumpWidth_range=closed_range(1, 0x80),
            PreScaler_range=closed_range(1, 256),
        ),
        CanPhase.Data:
        TimingInfo(
            Phase=CanPhase.Data,
            TimeSegment1_range=closed_range(1, 0x20),
            TimeSegment2_range=closed_range(1, 0x10),
            SyncJumpWidth_range=closed_range(1, 0x10),
            PreScaler_range=closed_range(1, 256),
        )
    },
    MaxFDBaudRate=2000,
    setter_offset_ts1=-1,
    setter_offset_ts2=-1,
    setter_offset_sjw=-1,
    setter_offset_prescaler=-1,
)

CANDeviceXCANPS = CanDevice(
    name="XCANPS",
    comment="Xilinx Zynq CAN periphery",
    F_in=80000000,
    MaxBaudRate=1000,
    TimingInfos={
        CanPhase.Arbitration:
        TimingInfo(
            Phase=CanPhase.Arbitration,
            TimeSegment1_range=closed_range(1, 16),
            TimeSegment2_range=closed_range(1, 8),
            SyncJumpWidth_range=closed_range(1, 4),
            PreScaler_range=closed_range(1, 256),
        )
    },
    setter_offset_ts1=-1,
    setter_offset_ts2=-1,
    setter_offset_sjw=-1,
    setter_offset_prescaler=-1,
)

CANDeviceSJA1000 = CanDevice(
    name="SJA1000",
    comment="SJA1000 compatible Opencores IP",
    F_in=24000000,
    MaxBaudRate=1000,
    TimingInfos={
        CanPhase.Arbitration:
        TimingInfo(
            Phase=CanPhase.Arbitration,
            TimeSegment1_range=closed_range(1, 16),
            TimeSegment2_range=closed_range(1, 8),
            SyncJumpWidth_range=closed_range(1, 4),
            PreScaler_range=closed_range(1, 64),
        ),
    },
    setter_offset_ts1=-1,
    setter_offset_ts2=-1,
    setter_offset_sjw=-1,
    setter_offset_prescaler=-1,
)


# device definitions
CanDeviceList: List[CanDevice] = [
    CANDeviceSJA1000,
    CANDeviceXCANFD,
    CANDeviceXCANPS
]


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
        self.scene.addText('TSEG1 (PROP+PHASE1)', font).setPos(x + bitTiming.TS1*w/2 - 5, -2*h)
        for tq in range(bitTiming.TS1):
            pos = QtCore.QPointF(x, 0)
            x += w
            rect = QtCore.QRectF(pos, size)
            self.scene.addRect(rect, pen, ts1Brush)
        self.scene.addText('TSEG2 (PHASE2)', font).setPos(x + bitTiming.TS2 * w / 2 - 5, -2*h)
        # sample point marker line:
        self.scene.addLine(x, 0, x, h*3, pen)
        self.scene.addLine(x - w*bitTiming.SyncJumpWidthActual, 0, x - w*bitTiming.SyncJumpWidthActual, h * 2, pen)
        self.scene.addLine(x + w * bitTiming.SyncJumpWidthActual, 0, x + w * bitTiming.SyncJumpWidthActual, h * 2, pen)
        self.scene.addText('Sampling point', font).setPos(x - 25, 3*h)
        self.scene.addText('-SJW', font).setPos(x - 20 - w*bitTiming.SyncJumpWidthActual, 2 * h)
        self.scene.addText('+SJW', font).setPos(x - 20 + w*bitTiming.SyncJumpWidthActual, 2 * h)
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
    def __init__(self, app: QtWidgets.QApplication):
        super().__init__()
        self.app = app
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
        self.sjw_value.setValue(1)
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
        for timingInfo in device.TimingInfos.values():
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

        self.bitTimingTable.setEnabled(False)
        self.app.processEvents()
        self.bitTimingTable.clearContents()
        self.canvas.scene.clear()
        self.bitTimingTable.setRowCount(0)
        f_in = int(self.f_in_MHz_value.value() * 1e6)
        timingInfo = None
        for _timingInfo in device.TimingInfos.values():
            if _timingInfo.Phase == self.currentPhase:
                timingInfo = _timingInfo
        if timingInfo is not None:
            bitTimingList = calculate_bit_timings(
                f_in=f_in,
                baud_rate_bps=self.currentBaudRateBps,
                target_sjw=self.sjw_value.value(),
                timing_info=timingInfo
            )
            for row, bitTiming in enumerate(bitTimingList):
                self.bitTimingTable.insertRow(row)
                item = QtWidgets.QTableWidgetItem(f'{bitTiming.SamplePoint:.3f}')
                item.setData(QtCore.Qt.UserRole, bitTiming)
                self.bitTimingTable.setItem(row, 0, item)
                self.bitTimingTable.setItem(row, 1, QtWidgets.QTableWidgetItem(f'{bitTiming.TimeQuantumSec*1e9:.3f}'))
                self.bitTimingTable.setItem(row, 2, QtWidgets.QTableWidgetItem(f'{bitTiming.TimeQuantaPerBitTime}'))
                device_setter = lambda rv, so: f"(device setvalue: {rv + so})" if so != 0 and rv > 0 else ""
                self.bitTimingTable.setItem(row, 3, QtWidgets.QTableWidgetItem(
                    f'{bitTiming.TS1:<6}{device_setter(bitTiming.TS1, device.setter_offset_ts1)}'
                ))
                self.bitTimingTable.setItem(row, 4, QtWidgets.QTableWidgetItem(
                    f'{bitTiming.TS2:<6}{device_setter(bitTiming.TS2, device.setter_offset_ts2)}'
                ))
                self.bitTimingTable.setItem(row, 5, QtWidgets.QTableWidgetItem(
                    f'{bitTiming.Prescaler:<6}{device_setter(bitTiming.Prescaler, device.setter_offset_prescaler)}'
                ))
                self.bitTimingTable.setItem(row, 6, QtWidgets.QTableWidgetItem(
                    f'{bitTiming.SyncJumpWidthActual:<6}{device_setter(bitTiming.SyncJumpWidthActual, device.setter_offset_sjw)}'
                ))
        self.bitTimingTable.setEnabled(True)
        self.app.processEvents()


def open_app():
    app = QtWidgets.QApplication(sys.argv)
    main_window = MainWindow(app)
    main_window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    open_app()
