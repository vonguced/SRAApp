from PyQt5 import uic
from PyQt5.QtWidgets import QWidget, QDoubleSpinBox, QSpinBox
from PyQt5.QtCore import pyqtSlot, pyqtSignal
from math import floor, ceil
import pyqtgraph as pg
import numpy as np

class QHistSelector(QWidget):
  '''
    Holds a histogram selector

    Args:
        data: Data for the histogram
        exp_pkg_fun: Function to get exp_pkg form selector
        parent: Parent of this widget
        title: Title of the histogram
        divisor: divisor for hist data
        bins: Bins for histogram

    Attributes:
        matches args

    Signals:
      setup_error(bool): Singal if something went wrong
                         while setup the selector
  '''

  setup_error = pyqtSignal(bool)
  reset_screen = pyqtSignal(bool)

  def __init__(self, data, exp_pkg_fun, *args, parent=None, title="lbl_title",
               divisor = 1, bins=100, **kwargs):
    super(QHistSelector, self).__init__(parent, *args, **kwargs)
    uic.loadUi('gui/ui/qhistselector.ui', self)
    self.lbl_title.setText(title)
    self.exp_pkg_fun = exp_pkg_fun
    self.data = data
    self.divisor = divisor
    self.isSet = False
    self._bins = int(bins)
    self._init()
    self.__connect_events()
    self.toggle_show()

  def _init(self):
    _set = self.__set_float()
    if not _set:
      print('error update')
      return False
    vals = self._get_values()
    if not vals:
      self._disable()
      return False
    self._min = floor(min(vals))
    self._max = ceil(max(vals))
    self.__setup_spin_boxes()
    self.__setup_slider()
    if not hasattr(self, 'max_line'):
      self._load_graph()
    else:
      self._bins_changed()
    self._enable()
    return True

  def update_data(self, data):
    '''Update data of selector'''
    self.data = data
    b = self._init()
    if b:
      self._enable()
      self.reset()

  def _disable(self):
    '''Disable selector'''
    p = self.graph_axis_bins.parentWidget()
    p.setHidden(True)
    self.setEnabled(False)
    self.setVisible(False)
    self.dbl_min.setValue(self.dbl_min.minimum())
    self.dbl_max.setValue(self.dbl_max.maximum())
    self.lbl_title.setStyleSheet("font-weight: normal;")

  def _enable(self):
    '''Enamble selector'''
    self.setEnabled(True)
    self.setVisible(True)
    self.dbl_min.setValue(self._min)
    self.dbl_max.setValue(self._max)

  def __set_float(self):
    try:
      raw_vals = self.data.values()
    except:
      self.setup_error.emit(True)
      print('error set float')
      return False
    #applie value divisor if there is one set before setting the float
    if self.divisor != 1 and self.divisor != 0:
      for k, v in self.data.items():
        self.data[k] = v/self.divisor
      raw_vals = self.data.values()
    if all([isinstance(i, int) for i in raw_vals]):
      self._float = 0
    else:
      if ceil(max(raw_vals)) <= 1:
        self._float = 3
      elif ceil(max(raw_vals)) <= 10:
        self._float = 2
      elif ceil(max(raw_vals)) <= 100:
        self._float = 1
      else:
        self._float = 0
    return True

  def __setup_spin_boxes(self):
    self.__set_sb_props(self.dbl_min)
    self.__set_sb_props(self.dbl_max)

  def __set_sb_props(self, sb):
    sb.setDecimals(self._float)
    sb.setSingleStep(1/(10**self._float))
    sb.setMaximum(self._max)
    sb.setMinimum(self._min)

  def __setup_slider(self):
    self.hist_range_slider.setMinimum(self.float2int(self._min))
    self.hist_range_slider.setMaximum(self.float2int(self._max))
    try:
      self.hist_range_slider.setStart(self.float2int(self._min))
      self.hist_range_slider.setEnd(self.float2int(self._max))
    except:
      pass

  def __connect_events(self):
    self.but_show.clicked.connect(self.toggle_show)
    self.but_reset.clicked.connect(self.reset)
    self.int_bins.valueChanged.connect(self._bins_changed)
    self.dbl_max.valueChanged.connect(self.update_slider_end)
    self.dbl_min.valueChanged.connect(self.update_slider_start)
    self.hist_range_slider.startValueChanged.connect(self.update_min_sb)
    self.hist_range_slider.endValueChanged.connect(self.update_max_sb)

  def reset(self):
    '''Reset selector'''
    self.graph.setXRange(self._min, self._max, padding=0)
    self.dbl_min.setValue(self._min)
    self.dbl_max.setValue(self._max)
    self.int_bins.setValue(self._bins)
    self.lbl_title.setStyleSheet("font-weight: normal;")
    self.but_reset.setEnabled(False)
    self.bool_exclusive.setChecked(True)
    self.isSet = False

  def set(self):
    '''Set selector'''
    self.lbl_title.setStyleSheet("font-weight: bold;")
    self.but_reset.setEnabled(True)
    try:
      self.min_line.setPos(self.dbl_min.value())
      self.max_line.setPos(self.dbl_max.value())
    except:
      pass
    self.isSet = True

  def get_exp_pkg(self):
    '''Get exp pkg from selector'''
    return set(self.exp_pkg_fun(self.dbl_min.value()*self.divisor,
                                self.dbl_max.value()*self.divisor,
                                self.bool_exclusive.isChecked()))

  def int2float(self, i):
    '''Convert int to float for spinbox'''
    if self._float <= 0:
      return i
    return i/(10**self._float)

  def float2int(self, f):
    '''Convert float to int for histogram'''
    if self._float <= 0:
      return f
    return int(f*(10**self._float))

  @pyqtSlot(int)
  def update_min_sb(self, i):
    '''Slot to update min spinbox'''
    f = self.int2float(i)
    self.dbl_min.setValue(f)
    self.set()

  @pyqtSlot(int)
  def update_max_sb(self, i):
    '''Slot to update max spinbox'''
    f = self.int2float(i)
    self.dbl_max.setValue(f)
    self.set()

  @pyqtSlot(int)
  @pyqtSlot(float)
  def update_slider_end(self, f):
    '''slot to update slider end'''
    i = self.float2int(f)  
    self.hist_range_slider.setEnd(i)
    self.set()
  
  @pyqtSlot(int)
  @pyqtSlot(float)
  def update_slider_start(self, f):
    '''slot to update slider start'''
    i = self.float2int(f)
    self.hist_range_slider.setStart(i)
    self.set()

  def toggle_show(self):
    '''Hide/Show the hist'''
    p = self.graph_axis_bins.parentWidget()
    p.setHidden(not p.isHidden())
    self.reset_screen.emit(p.isHidden())

  def _get_values(self):
    '''Get the values from self.data'''
    try:
      raw_vals = self.data.values()
    except:
      print('error get vals')
      self.setup_error.emit(True)
      return None
    if self._float <= 0:
      return [int(round(i,0)) for i in raw_vals]
    return [float(i) for i in raw_vals]

  def _load_graph(self):
    '''Setup Graph'''

    #set properties of hist
    self.graph.setBackground('w')
    #padding = 0 so they match with the sliders and labels
    self.graph.setXRange(self._min, self._max, padding=0)
    self.graph.hideAxis('bottom')
    self.graph.hideAxis('left')

    #set pen for lines and make lines
    pen = pg.mkPen(color=(255, 0, 0), width=1)
    self.min_line = pg.InfiniteLine(pos=self._min, angle=90, pen=pen)
    self.max_line = pg.InfiniteLine(pos=self._max, angle=90, pen=pen)

    #plot data
    self._bins_changed()

    #plot vertical lines
    self.graph.addItem(self.max_line)
    self.graph.addItem(self.min_line)

  def _bins_changed(self):
    '''Handle change event for bins'''
    if hasattr(self, 'curve'):
      self.graph.removeItem(self.curve)
    #check for post process otherwise abort
    vals = self._get_values()
    if not vals:
      return None
    y,x = np.histogram(vals, bins=np.linspace(self._min, self._max,
                      self.int_bins.value()+1))
    self.curve = pg.PlotCurveItem(x, y, stepMode=True, fillLevel=0, 
                                  brush=(0, 0, 255, 80))
    
    self.graph.setYRange(0, max(y), padding=0)
    self.y_max.setText(str(np.round(max(y),0)))
    self.y_min.setText(str(np.round(min(y),0)))

    self.graph.addItem(self.curve)





