from PyQt5 import uic
from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QAbstractTableModel, pyqtSignal
import operator

class SelectorTableModel(QAbstractTableModel):
  '''
    Model for the selector tables

    Args:
        parent (qwidget): Parent widget calling this class
        data (list): List of lists of data to display in Selector
        header (list): List of headers for different data columns

    Attributes:
        data (list): List of lists of data
        header (list): List of header strings
  '''

  def __init__(self, parent, data, header, *args):
    QAbstractTableModel.__init__(self, parent, *args)
    self.data = data
    self.header = header
    self.sort(0,Qt.AscendingOrder)

  def rowCount(self, parent):
    '''count rows of data'''
    return len(self.data)

  def columnCount(self, parent):
    '''count columns of data'''
    if self.rowCount(parent) == 0:
      return 0
    return len(self.data[0])

  def data(self, index, role):
    '''Overwrite inherited method to customize how the data is displayed
    Align numbers right
    Align strings left'''
    if not index.isValid():
      return None
    if role == Qt.DisplayRole:
      value = self.data[index.row()][index.column()]
      return value
    if role == Qt.TextAlignmentRole:
      value = self.data[index.row()][index.column()]
      if isinstance(value, int) or isinstance(value, float):
        # Align right, vertical middle.
        return Qt.AlignVCenter + Qt.AlignRight
      if isinstance(value, str):
        # Align left, vertical middle.
        return Qt.AlignVCenter + Qt.AlignLeft
      return value
    return None

  def headerData(self, col, orientation, role):
    '''Overwrite inherited method to display custom headers'''
    if orientation == Qt.Horizontal and role == Qt.DisplayRole:
      return self.header[col]
    return None

  def sort(self, col, order):
    '''Overwrite inherited method for custom sort
    sort by respective column selected for sorting'''
    self.layoutAboutToBeChanged.emit()
    self.data = sorted(self.data,
                       key=operator.itemgetter(col))
    self.sortedBy = {'col':col,'order':Qt.AscendingOrder}
    if order == Qt.DescendingOrder:
      self.data.reverse()
      self.sortedBy = {'col':col,'order':Qt.DescendingOrder}
    self.layoutChanged.emit() 

  def popRows(self, rows):
    '''remove rows from data'''
    res = []
    self.layoutAboutToBeChanged.emit()
    for idx in reversed(sorted(rows)):
      res.append(self.data.pop(idx))
    self.layoutChanged.emit() 
    return res

  def appendRows(self, rows):
    '''append rows to data'''
    self.layoutAboutToBeChanged.emit()
    for row in rows:
      self.data.append(row)
    self.layoutChanged.emit()


class Selector(QWidget):
  '''
    QWidget for Selectors - Contains tow SelecotrTables

    Args:
        parent_but: Button which holds this selector
        cql_function: Function to convert selector data to exp_pkg
        title (str): Title for QWidget
        data (list): List of lists of data to display in table
        header (list): List of header strings for data

    Attributes:
        result (list): List of selected data
        isSet (bool): Bool if selector is set
        cql_function: Holds the cql_function
  '''

  change_occured = pyqtSignal(bool)

  def __init__(self, parent_but, cql_function, title, data, header):
    super(Selector, self).__init__()
    self.setWindowModality(Qt.ApplicationModal)
    uic.loadUi('gui/ui/selector_gui.ui', self)
    self.lbl_selector.setText(title)
    self.parent_but = parent_but
    self.result = []
    self.cql_function = cql_function
    self.isSet = False
    self.setup_tableview(data, header)
    self._connect_events()

  def set(self):
    '''Set result and fonts for a set selector'''
    self.result = self.tbl_selected.model().data
    if not self.result:
      self.parent_but.setStyleSheet("font-weight: normal;")
      self.isSet = False
      self._close()
    else:
      self.parent_but.setStyleSheet("font-weight: bold;")
      self.isSet = True
      self._close()

  def reset(self):
    '''Reset a selector'''
    self.but_deselect_all.click()
    self.bool_exclusive.setChecked(True)
    self.cancel()

  def _close(self):
    '''Close the selector'''
    self.change_occured.emit(True)
    self.close()

  def cancel(self):
    '''Cancel the selector'''
    self.isSet = False
    self.parent_but.setStyleSheet("font-weight: normal;")
    self.result = []
    self._close()

  def disconnect(self):
    '''Dissconect selector from button'''
    self.parent_but.clicked.disconnect()

  def get_exp_pkg(self):
    '''Get experiment package from selector'''
    i = self.result[0]
    #get column if no count column or only one data column
    if len(i) == 1 or len(i) == 2:
      return set(self.cql_function([i[0] for i in self.result],
                                   self.bool_exclusive.isChecked()))
    #get all columns except count column if there are more
    return set(self.cql_function([i[0:len(i)-1] for i in self.result],
                                 self.bool_exclusive.isChecked()))


  def setup_tableview(self, data, header):
    '''Setup both tableviews'''
    self.data = data
    self.tbl_available.setModel(SelectorTableModel(self, data, header))
    self.tbl_available.resizeColumnsToContents()
    self.tbl_selected.setModel(SelectorTableModel(self, [], header))
    self.tbl_selected.resizeColumnsToContents()
    if not self.data:
      self.parent_but.setEnabled(False)
    else:
      self.parent_but.setEnabled(True)

  def _connect_events(self):
    '''Connect events of buttons present in this q widget'''
    self.but_select.clicked.connect(
      lambda: self.move_selected_rows(self.tbl_available, self.tbl_selected))
    self.but_select_all.clicked.connect(
      lambda: self.move_all(self.tbl_available, self.tbl_selected))
    self.but_deselect.clicked.connect(
      lambda: self.move_selected_rows(self.tbl_selected, self.tbl_available))
    self.but_deselect_all.clicked.connect(
      lambda: self.move_all(self.tbl_selected, self.tbl_available))
    self.but_clear_selection.clicked.connect(self.clear_selections)
    self.but_cancel.clicked.connect(self.cancel)
    self.but_set_selection.clicked.connect(self.set)
    self.parent_but.clicked.connect(self.show)

  def clear_selections(self):
    '''Clear all selections from both tables'''
    self.tbl_available.selectionModel().clearSelection()
    self.tbl_selected.selectionModel().clearSelection()

  def move_selected_rows(self, f, t):
    '''Move selected rows from f table to t table'''
    rows = [r.row() for r in f.selectionModel().selectedRows()]
    self._move_rows(f, t, rows)

  def move_all(self, f, t):
    '''Move all rows from f table to t table'''
    nrows = f.model().rowCount(f)
    self._move_rows(f, t, list(reversed(range(nrows))))

  def _move_rows(self, f, t, rows):
    '''Helper function to move rows from f table to t table'''
    f.selectionModel().clearSelection()
    t.model().appendRows(f.model().popRows(rows))
    t.model().sort(**f.model().sortedBy)
    t.resizeColumnsToContents()

  def __changes(self):
    if len(self._curr) != len(self.result):
        return True
    return sorted(self._curr) != sorted(self.result)

