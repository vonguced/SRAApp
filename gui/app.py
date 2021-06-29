"""Ui Classes of SRA App

This module contains all the ui classes needed for the SRA-App.

The main Ui Class provides the entry point to the app.
This module exports the following classes:

LoadingDB_Thread: a pyqt5 threaded class inherited 
                  from the LoadingDB Class of the database module
Connection_Thread: A class which checks periodically the 
                   connection to the neo4j database
LED_styles: Provies styles for LEDs in qwidgets
SelectorTableModel: Provies the model for the selector tables
Selector: QWidget for Selector subwindows
Ui: QMainWindow for SRA-App
"""

from PyQt5 import uic
from PyQt5.QtWidgets import (QApplication, QWidget, QPushButton, 
                             QMessageBox, QMainWindow, QVBoxLayout)
from PyQt5.QtCore import (Qt, QAbstractTableModel, pyqtSignal, 
                          QThread, QObject, pyqtSlot)
from database.db_classes import *
from database.xml_keywords import *
from database.load_db import LoadingDB, PostProcessingDB
from gui.widgets.qhistselector import QHistSelector
from gui.widgets.qselector import Selector
from gui.widgets.qexport import Export
from re import match
import subprocess
import logging
from time import sleep

class Connection_Thread(QThread):
  '''
    Threaded connection checker to Neo4j DB

    Args:
        parent (qwidget): Parent widget calling this class
        neo (SRAMetadataDB): Neo4j DB to check connection to

    Attributes:
        alive_neo4j (bool): Signal if DB is up
        _neo (SRAMetadataDB): Attribute for Neo4j DB
        _abort (bool): Boolean to flag an abortion of the worker
  '''

  alive_neo4j = pyqtSignal(bool)

  def __init__(self, parent=None, neo=None):
        super().__init__()
        self._neo = neo
        self._abort = False

  def run(self):
    '''Check connection to Neo4j DB every second by matching a random node'''
    while True:
      try:
        self._neo.unsafe_run_cql("MATCH (n) RETURN n LIMIT 1")
        self.alive_neo4j.emit(True)
      except Exception:
        self.alive_neo4j.emit(False)
      QApplication.processEvents()
      if self._abort:
        break
      sleep(2)

  @pyqtSlot()
  def abort(self):
    '''Set abort flag so worker quits with the next try'''
    self._abort = True


class LED_styles():
  '''
    Styles for QWidget LEDs
  '''

  def __init__(self):
    super(LED_styles, self).__init__()
  
  def red(self):
    '''Defines a red led'''
    return self._default().format(start="#ffb8b8",stop="#f00")

  def green(self):
    '''Defines a green led'''
    return self._default().format(start="#d9ffdc",stop="#03fc17")

  def _default(self):
    '''Defines basic LED style'''
    s = """QLabel {{
    color: #F00;
    border-radius: 7px;
    background: qradialgradient(
        cx: 0.3, cy: -0.4, fx: 0.3, fy: -0.4,
        radius: 1.35, stop: 0 {start}, stop: 1 {stop}
        );
    }}"""
    return s


class Ui(QMainWindow):
    '''
    Main Window for SRA-App

    Args:
        host (str): Networkpath to neo4j db
        user (str): Username for neo4j db
        dbpass (str): Password for neo4j db
        neo4j_home (str): Path to bin folder of neo4j
        entrez (Entrez): Entrez Class with set e-mail.
                         (NCBI's Entrez functionality 
                          to fetch data from their db)

    Attributes:
        The class provides the args as attributes as described above

    Signals:
      sig_abort: Signal to abort the connection check worker
      sig_abort_load: Signal to abort load/pp woker
    '''

    sig_abort = pyqtSignal()
    sig_abort_load = pyqtSignal()

    def __init__(self, host, user, dbpass, neo4j_home, entrez,
                 raw_db_name = "raw", subset_db_name = "subset",
                 parent_logger_name = ""):
        super(Ui, self).__init__()
        self.logger_name = '{}.Ui'.format(parent_logger_name)
        self.logger = logging.getLogger(self.logger_name)
        if not bool(match("^[a-z0-9]*$", raw_db_name)):
          raise ValueError(f"ValueError raw_db_name: '{raw_db_name}' "
                           "can only contain numbers and lowercase characters")
        self.raw_db_name = raw_db_name
        if not bool(match("^[a-z0-9]*$", subset_db_name)):
          raise ValueError(f"ValueError subset_db_name: '{subset_db_name}' "
                           "can only contain numbers and lowercase characters")
        self.subset_db_name = subset_db_name
        self.export = Export(self)
        self.host = host
        self.user = user
        self.dbpass = dbpass
        self.neo4j_home = neo4j_home
        self.entrez = entrez
        self.setWindowModality(Qt.ApplicationModal)
        uic.loadUi('gui/ui/main_gui.ui', self)
        self.led = LED_styles()
        if not self._connect_databases():
          self._deactivate()
        else:
          if self.subset.count_nodes() != 0:
            self.but_use_raw.setEnabled(True)
            self._safe_connect_button(self.but_use_raw, self.use_subset)
          self.db_in_use = self.raw_stats
          if self.raw.count_nodes() != 0:
            pp = PostProcessingDB(self.db_in_use.db, self.entrez,
                                parent_logger_name=self.logger_name)
            if not pp.check_db_status():
              raise ValueError("Database seems to be corrupted. "
                             "Consider deleting it manually")
          self._update_ui_db(initial=True)
        self.show()

    def close_main(self):
      '''Close the App'''
      self._abort()
      self.close()

    def _start_connection_check(self):
        '''Start the threaded connection check'''
        self.con_was_alive = True
        worker = Connection_Thread(neo=self.raw)
        self._threads['connection'] = worker
        worker.alive_neo4j.connect(self._check_connection)
        self.sig_abort.connect(worker.abort)
        worker.start()
        self.logger.info("Connection worker started")

    @pyqtSlot(bool)
    def _check_connection(self, alive):
      '''Handle signal from connection check'''
      if not alive:
        self.status_subset_DB.setStyleSheet(self.led.red())
        self.status_rawdata_DB.setStyleSheet(self.led.red())
        if self.con_was_alive:
          self.update_status_bar("Lost connection to DB", logging.WARNING)
          self._set_db_interaction(False)
      else:
        self.status_subset_DB.setStyleSheet(self.led.green())
        self.status_rawdata_DB.setStyleSheet(self.led.green())
        self._update_subset_status()
        self._update_raw_status()
        if not self.con_was_alive:
          self.update_status_bar("")
          self.logger.info("Reconnected to DB - "
                           "Restart app to make sure it "
                           "works correctly.")
          self._set_db_interaction(True)
          self.use_raw()
      self.con_was_alive=alive
    
    def _set_db_interaction(self, enable):
      '''Disable/Enable interaction with the db form the app'''
      self.but_subset_database.setEnabled(enable)
      self.but_export.setEnabled(enable)
      self.but_clear_load.setEnabled(enable)
      self.txt_search.setEnabled(enable)
      self.but_use_raw.setEnabled(False)
      if enable:
        sleep(5)
        if self.subset.count_nodes() != 0:
          self.but_use_raw.setEnabled(True)

    @pyqtSlot()
    def _abort(self):
        '''Stop the periodic connection check'''
        self.sig_abort.emit()
        self.sig_abort_load.emit()
        self.logger.info("Waiting on worker to finish")
        try:
          for thread in self._threads.values():
            thread.quit()
            thread.wait()
        except:
          pass
        self.logger.info("Worker closed")

    def _deactivate(self):
      '''Deactivate buttons of app - No connection to db'''
      self._enable_buttons(self.children(), disable=True)
      self.txt_search.setEnabled(False)
      self.done.clicked.connect(self.close_main)
      self.done.setEnabled(True)
      self.but_retry.setHidden(False)
      self.but_retry.setEnabled(True)
      self.but_retry.clicked.connect(self._retry)
      self.but_clear_load.setEnabled(False)

    def _retry(self):
      '''Retry connection to database if there was no connection'''
      if not self._connect_databases():
        return None
      self._enable_buttons(self.children())
      self.done.clicked.disconnect()
      self.but_clear_load.setEnabled(True)
      self.txt_search.setEnabled(True)
      self.but_use_raw.setEnabled(False)
      self.but_reset_selectors.setEnabled(False)
      #self.but_reset_slider.setEnabled(False)
      #self.but_reset_prop.setEnabled(False)
      self.update_status_bar("")
      if self.subset.count_nodes() != 0:
        self.but_use_raw.setEnabled(True)
        self._safe_connect_button(self.but_use_raw, self.use_subset)
      self.db_in_use = self.raw_stats
      # self._show_progress(False)
      self._update_ui_db(initial=True)

    def _enable_buttons(self, l, disable=False):
      '''Disable/Enable all buttons'''
      for i in l:
        if isinstance(i, QPushButton):
          i.setEnabled(not disable)
        else:
          self._enable_buttons(i.children(), disable)

    def show_info(self):
      '''Show app info'''
      msgBox = QMessageBox()
      msgBox.setIcon(QMessageBox.Information)
      msgBox.setText("Cédric von Gunten\n"+
      "https://github.com/vonguced/SRAApp\n"+
      "Master's Thesis 2021 @ ZHAW")
      msgBox.setWindowTitle("Information")
      msgBox.setStandardButtons(QMessageBox.Ok)
      msgBox.exec()

    def _update_ui_db(self, initial=False):
      '''Update the whole ui e.g. after a connection loss'''
      self._setup_selectors()
      if initial:
        self.but_export.setText('Export from {}'.format(self.raw_db_name))
        self.but_use_raw.setText("Use {} DB for Histogram "
                               "and Selectors".format(self.subset_db_name))
        self.but_subset_database.setText("Subset {} "
                                       "DB".format(self.raw_db_name))
        self._connect_events()
        self._set_hist_selectors()
        self._threads = {}
        self._start_connection_check()
        self.but_retry.setHidden(True)
        self.but_retry.setEnabled(False)
        self._show_progress(False)
      self._reset_hist_selectors()

    def use_subset(self):
      '''Use the subset DB for display and selectors'''
      self.db_in_use = self.subset_stats
      self._safe_connect_button(self.but_use_raw, self.use_raw)
      self._change_db(self.raw_db_name, self.subset_db_name)

    def use_raw(self):
      '''Use the raw DB for display and selectors'''
      self.db_in_use = self.raw_stats
      self._safe_connect_button(self.but_use_raw, self.use_subset)
      self._change_db(self.subset_db_name, self.raw_db_name)

    def _change_db(self, fname, tname):
      self.but_use_raw.setText(f"Use {fname} DB for Histogram "
                               "and Selectors")
      self.but_export.setText(f'Export from {tname}')
      self.but_subset_database.setText(f"Subset {tname} DB")
      self._disconnect_selectors()
      self.but_reset_selectors.click()
      self._update_ui_db()

    def _safe_connect_button(self, but, con):
      '''Disconnect before reconnecting as mult. connection may exist'''
      but.disconnect()
      but.clicked.connect(con)

    def _setup_selectors(self):
      '''Setup the selectors and their selector tables'''
      self.tax_sel = Selector(
        self.but_taxonomic_id,
        self.db_in_use.exp_pkg_tax_ids,
        'Taxonomic IDs',
        #only for taxonomic ids to make sort correct
        [(int(i),j) for i, j in self.db_in_use.taxon_ids()],
        ['Taxonomic ID', 'Occurrences'])
      self.sci_sel = Selector(
        self.but_scientific_name,
        self.db_in_use.exp_pkg_sci_names,
        'Scientific Names',
        self.db_in_use.scientific_names(),
        ['Scientific Name', 'Occurrences'])
      self.org_sel = Selector(
        self.but_organization,
        self.db_in_use.exp_pkg_org_names,
        'Organizations',
        [(i,) for i in set(self.db_in_use.organizations())],
        ['Organization'])
      self.str_sel = Selector(
        self.but_strains,
        self.db_in_use.exp_pkg_strains,
        'Strains',
        self.db_in_use.strains(),
        ['Strain', 'Occurrences'])
      self.pty_sel = Selector(
        self.but_platform_types,
        self.db_in_use.exp_pkg_plt_types,
        'Platform Types', 
        self.db_in_use.platform_types(),
        ['Platform Type', 'Occurrences'])
      self.pmo_sel = Selector(
        self.but_platform_models,
        self.db_in_use.exp_pkg_plt_models,
        'Platform Models',
        [(i,) for i in set(self.db_in_use.platform_models())],
        ['Platform Model'])
      self.lst_sel = Selector(
        self.but_library_strategy,
        self.db_in_use.exp_pkg_lib_strats,
        'Library Strategies',
        self.db_in_use.library_strategies(),
        ['Library Strategie', 'Occurrences'])
      self.lla_sel = Selector(
        self.but_library_layout,
        self.db_in_use.exp_pkg_lib_layouts,
        'Library Layouts',
        self.db_in_use.library_layouts(),
        ['Library Layout', 'Occurrences'])
      self.env_sel = Selector(
        self.but_env_material,
        self.db_in_use.exp_pkg_env_material,
        'Environmental Material',
        self.db_in_use.env_material(),
        ['Environmental Material', 'Occurrences'])
      self.asb_sel = Selector(
        self.but_assembly_submission,
        self.db_in_use.exp_pkg_assembly_submission_date,
        'Assembly Subission Date',
        self.db_in_use.assembly_submission_date(),
        ['Assembly Submission Date', 'Occurrences'])
      self.rda_sel = Selector(
        self.but_sradate,
        self.db_in_use.exp_pkg_sra_date,
        'SRA File Date',
        self.db_in_use.sra_date(),
        ['SRA File Date', 'Occurrences'])
      self.sty_sel = Selector(
        self.but_sample_type,
        self.db_in_use.exp_pkg_sample_type,
        'Sample Type',
        self.db_in_use.sample_type(),
        ['Sample Type', 'Occurrences'])
      self.hos_sel = Selector(
        self.but_host,
        self.db_in_use.exp_pkg_host,
        'Host',
        self.db_in_use.host(),
        ['Host', 'Occurrences'])
      self.iso_sel = Selector(
        self.but_isolate_source,
        self.db_in_use.exp_pkg_isolation_source,
        'Isolation Source',
        self.db_in_use.isolation_source(),
        ['Isolation Source', 'Occurrences'])
      self.ina_sel = Selector(
        self.but_isolate_name,
        self.db_in_use.exp_pkg_isolate_name_alias,
        'Isolation Name',
        self.db_in_use.isolate_name_alias(),
        ['Isolation Name', 'Occurrences'])
      self.glo_sel = Selector(
        self.but_geo_loc,
        self.db_in_use.exp_pkg_geo_loc_name,
        'Geological Location',
        self.db_in_use.geo_loc_name(),
        ['Country', 'Location', 'Occurrences'])
      self.cod_sel = Selector(
        self.but_collection_date,
        self.db_in_use.exp_pkg_collection_date,
        'Collection Date',
        self.db_in_use.collection_date(),
        ['Collection Date', 'Occurrences'])
      self.selectors = [self.tax_sel, self.sci_sel, self.org_sel,
                        self.str_sel, self.pty_sel, self.pmo_sel,
                        self.lst_sel, self.lla_sel, self.env_sel,
                        self.asb_sel, self.sty_sel, self.hos_sel,
                        self.iso_sel, self.ina_sel, self.glo_sel,
                        self.cod_sel, self.rda_sel]
      [sel.change_occured.connect(self._selector_changed)
       for sel in self.selectors]

    @pyqtSlot(bool)
    def _selector_changed(self, changed):
      '''Slot when a selector has changed'''
      if not changed:
        return None
      if all([not sel.isSet for sel in self.selectors]) & (
         not self.bool_assembly.checkState()):
        self.but_reset_selectors.setEnabled(False)
      else:
        self.but_reset_selectors.setEnabled(True)

    def _set_hist_selectors(self):
      '''Setup histogram selectors'''
      self._gc_ratio = QHistSelector(
        data = self.db_in_use.gc_ratios(),
        exp_pkg_fun = self.db_in_use.exp_pkg_gc_ratios,
        parent=self, title='GC-Ratios')
      self._ably_count = QHistSelector(
        data = self.db_in_use.assembly_contig_count(),
        exp_pkg_fun = self.db_in_use.exp_pkg_assembly_contig_count,
        parent=self, title='Assembly Contig Count')
      self._ably_n50 = QHistSelector(
        data = self.db_in_use.assembly_n50(),
        exp_pkg_fun = self.db_in_use.exp_pkg_assembly_n50,
        parent=self, title='Assembly N50 / kilo',
        divisor = 1000)
      self._ably_l50 = QHistSelector(
        data = self.db_in_use.assembly_l50(),
        exp_pkg_fun = self.db_in_use.exp_pkg_assembly_l50,
        parent=self, title='Assembly L50')
      self._n_bases = QHistSelector(
        data = self.db_in_use.n_bases(),
        exp_pkg_fun = self.db_in_use.exp_pkg_n_bases,
        parent=self, title="#N in Bases / Mega",
        divisor = 1000000)
      self._count_bases = QHistSelector(
        data = self.db_in_use.count_bases(),
        exp_pkg_fun = self.db_in_use.exp_pkg_count_bases,
        parent=self, title="# Total Bases / Giga",
        divisor = 1000000000)
      self.all_hist_selectors = [self._ably_count, self._ably_n50,
                                 self._ably_l50, self._gc_ratio,
                                 self._n_bases, self._count_bases]
      self.layout = QVBoxLayout()
      self.layout.setContentsMargins(0,0,0,0)
      for hsel in self.all_hist_selectors:
        hsel.reset_screen.connect(self._reset_screen)
        self.layout.addWidget(hsel)
      self.hist_selectors.setLayout(self.layout)

    def _reset_hist_selectors(self):
      '''Reset histogram selectors'''
      self._gc_ratio.update_data(self.db_in_use.gc_ratios())
      self._ably_count.update_data(self.db_in_use.assembly_contig_count())
      self._ably_n50.update_data(self.db_in_use.assembly_n50())
      self._ably_l50.update_data(self.db_in_use.assembly_l50())
      self._n_bases.update_data(self.db_in_use.n_bases())
      self._count_bases.update_data(self.db_in_use.count_bases())

    @pyqtSlot(bool)
    def _reset_screen(self, b):
      '''Check if screen should be reset after hiding hsel'''
      if b:
        self.resize(self.sizeHint())

    def _connect_events(self):
      '''Connect all buttons of Ui'''
      self.but_info.clicked.connect(self.show_info)
      self.done.clicked.connect(self.close_main)
      self.bool_assembly.stateChanged.connect(self._assembly_changed)
      self.but_reset_selectors.clicked.connect(self._reset_selectors)
      self.but_subset_database.clicked.connect(self._subset_database)
      self.but_export.clicked.connect(self.export.show)
      self.but_clear_load.clicked.connect(self._load_raw_database)
      self.txt_search.textChanged.connect(self._search_changed)
      self.but_load_abort.clicked.connect(self._abort_load)

    def _disconnect_selectors(self):
      '''Disconnect all selectors'''
      [sel.disconnect() for sel in self.selectors]

    def _reset_selectors(self):
      '''Reset all selectors'''
      [sel.reset() for sel in self.selectors]
      self.bool_assembly.setChecked(False)
      self.but_reset_selectors.setEnabled(False)

    def _search_changed(self, text):
      '''Change in search bar handler'''
      if text == "":
        self.but_clear_load.setEnabled(False)
      else:
        self.but_clear_load.setEnabled(True)

    def _connect_databases(self):
      '''Connect raw and subset database'''
      try:
        self.system = SRAMetadataDB(self, self.host, self.user,
                                    self.dbpass, "system")
      except:
        msg = ("Neo4j not found with network:{}, user:{}. "
               "Make sure Neo4j is running in the background")
        self.update_status_bar(msg.format(self.host,self.user),
                               logging.WARNING)
        return False
      self.raw = self._connect_database(self.raw_db_name,
                                        self.status_rawdata_DB,
                                        self.lbl_rawdata_DB)
      if self.raw:
        self.raw_stats = DBStatistics(self.raw)
      self.subset = self._connect_database(self.subset_db_name,
                                           self.status_subset_DB,
                                           self.lbl_subset_DB)
      if self.subset:
        self.subset_stats = DBStatistics(self.subset)
      return True

    def _connect_database(self,name,status_led,status_lbl, retry=0):
      '''Connect specific database and handle retries - 
      create db if it does not exist'''
      try:
        db = SRAMetadataDB(self, self.host, self.user, self.dbpass, name)
        nodes = db.count_nodes()
        if isinstance(nodes, int):
          status_led.setStyleSheet(self.led.green())
          status_lbl.setText(status_lbl.text().format(nodes=nodes))
        return db
      except:
        if (name == self.subset_db_name) & (retry==0):
          self.system.run_cql("create database {}".format(self.subset_db_name))
          self.update_status_bar("Created {} DB as it "
                                 "did not exist".format(self.subset_db_name))
          return self._connect_database(name, status_led, status_lbl,1)
        elif (name == self.raw_db_name) & (retry==0):
          self.system.run_cql("create database {}".format(self.raw_db_name))
          self.update_status_bar("Created {} DB as it "
                                 "did not exist".format(self.raw_db_name))
          return self._connect_database(name, status_led, status_lbl,1)
        else:
          status_led.setStyleSheet(self.led.red())
          status_lbl.setText(status_lbl.text().format(nodes=""))
      return None

    def update_status_bar(self, msg, level=logging.INFO):
      '''Update the status bar with a specified msg 
      and put that msg into the logger'''
      self.statusBar().showMessage(msg)
      if msg != "":
        if (level == logging.INFO):
          self.logger.info(msg)
        elif level == logging.WARNING:
          self.logger.warning(msg)
        elif level == logging.ERROR:
          self.logger.error(msg)
        else:
          self.logger.debug(msg)
      QApplication.processEvents()

    def _update_subset_status(self):
      '''Update the subset node count'''
      s = self.subset.count_nodes()
      r = self.subset_db_name
      self.lbl_subset_DB.setText(f"{r} DB (Nodes: {s})")

    def _update_raw_status(self):
      '''Update the raw node count'''
      s = self.raw.count_nodes()
      r = self.raw_db_name
      self.lbl_rawdata_DB.setText(f"{r} DB (Nodes: {s})")

    def _assembly_changed(self):
      '''Handle change event for assembly bool'''
      self._selector_changed(True)

    def _log_subprocess_out(self, stdout):
      '''Logger for the subprocess output'''
      for line in iter(stdout.readline, b''):
        self.logger.info('subprocess out: %r', line)

    def _copy_subset_db(self):
      '''Copy the subset db from raw db'''
      r = self.raw_db_name
      s = self.subset_db_name
      self._abort()
      self.update_status_bar(f"Droping {s} DB")
      self.system.run_cql(f"drop database {s}")
      self.update_status_bar(f"Stopping {r} DB")
      self.system.run_cql(f"stop database {r}")
      self.update_status_bar(f"Copy {r} DB to {s} DB")
      QApplication.processEvents()
      neohome = self.neo4j_home
      cql_copy = (f"{neohome}bin/neo4j-admin copy --from-database={r} "
                                                 f"--to-database={s}")
      pro = subprocess.Popen([cql_copy], shell=True,
                     stdout=subprocess.PIPE, 
                     stderr=subprocess.STDOUT)
      with pro.stdout:
        self._log_subprocess_out(pro.stdout)
      exitcode = pro.wait() # 0 means success
      self.update_status_bar(f"Linking {s} DB for neo4j")
      self.system.run_cql(f"create database {s}")
      self.update_status_bar(f"Starting {r} DB")
      self.system.run_cql(f"start database {r}")
      self._start_connection_check()
      if self.raw.count_nodes() != self.subset.count_nodes():
        self.update_status_bar("Copy did not succeed - "
                               "did you start the app "
                               "with the correct neo4j project?",
                               level=logging.ERROR)
        return False
      return True

    def get_exp_pkgs(self):
      '''Get list of all experiment packages form db for selected properties'''
      exp_pkg_sets = []
      #check assembly
      if self.bool_assembly.checkState():
        exp_pkg_sets.append(set(self.db_in_use.exp_pkg_assembly()))
      #check selectors
      for sel in self.selectors:
        if sel.isSet and (len(sel.result) != 0):
          exp_pkg_sets.append(sel.get_exp_pkg())
      #check hist selectors
      for hsel in self.all_hist_selectors:
        if hsel.isSet | (not ((hsel.dbl_min.value() == hsel.dbl_min.minimum()) &
                              (hsel.dbl_max.value() == hsel.dbl_max.maximum()))):
          exp_pkg_sets.append(hsel.get_exp_pkg())
      if not exp_pkg_sets:
        return []
      return list(exp_pkg_sets[0].intersection(*exp_pkg_sets))

    def _reduce_to_subgraph(self, exp_pkgs):
      '''Reduce subset db to match selected exp_pkgs only'''
      cqls = []
      cqls.append("match (n) set n._keep = 0")
      cqls.append("match (n) where n.exp_pkg "
                  "in {} set n._keep = 1".format(exp_pkgs))
      cqls.append("match (p:platform)--(e:experiment)-"
                  "-(sub:submission)--(sam:sample)-"
                  "-(e)--(stu:study)--(org:organization) "
                  "where e._keep = 1 "
                  "with [x in collect(p)+collect(sub)+collect(sam)+"
                  "collect(stu)+collect(org)] as keep "
                  "foreach(node in keep | set node._keep = 1)")
      cqls.append("optional match (sam:sample)--(satt:sample_attrib) "
                  "where sam._keep = 1 set satt._keep = 1")
      cqls.append("optional match (c:cloud_file)--(r) "
                  "where r._keep = 1 set c._keep = 1")
      cqls.append("optional match (sra:sra_file)--(r) "
                  "where r._keep = 1 set sra._keep = 1")
      cqls.append("optional match (sam:sample)--(a:assembly)-"
                  "-(ast:assembly_stats) "
                  "where sam._keep = 1 set a._keep = 1 "
                  "set ast._keep = 1")
      cqls.append("match (n) where n._keep = 0 detach delete n")
      cqls.append("match (n) remove n._keep ")
      for cql in cqls:
        self.subset.run_cql(cql)

    def _subset_database(self):
      '''Subset the selected db to match selectors and properites'''
      exp_pkgs = self.get_exp_pkgs()
      if not exp_pkgs:
        self.update_status_bar("Filters produce an empty set - try to remove "
                               "some filter(s) to generate the subgraph")
        return None
      self.setEnabled(False)
      s = "Subset {} DB".format(self.raw_db_name)
      if self.but_subset_database.text() == s:
        b = self._copy_subset_db()
        self._update_subset_status()
        if not b:
          self.setEnabled(True)
          return None
      QApplication.processEvents()
      self.update_status_bar("Filtering {} graph".format(self.subset_db_name))
      QApplication.processEvents()
      self._reduce_to_subgraph(exp_pkgs)
      self.update_status_bar("")
      self._update_subset_status()
      QApplication.processEvents()
      self.setEnabled(True)
      self.but_use_raw.setEnabled(True)
      self.use_subset()
      self.but_reset_selectors.click()

    def _show_progress(self, b):
      '''Set hidden/visibla for progress bar'''
      self.h_searching.setHidden(b)
      self.h_progress.setHidden(not b)

    @pyqtSlot(str)
    def _status_update(self, msg):
      '''Slot to update status bar'''
      self.update_status_bar(msg)

    @pyqtSlot(str, int, int)
    def _prog_update(self, title, i, m):
      '''Slot to update progress bar'''
      self.lbl_prog_bar_title.setText(title)
      self.prog_bar.setMaximum(m)
      self.prog_bar.setValue(i)
      self.lbl_prog_bar.setText("{}/{}".format(i, m))

    @pyqtSlot(bool)
    def _finish_pp(self, success):
      '''Slot after a finished post process'''
      if not success:
        self.update_status_bar("Postprocessing did not succeed - "
                               "delete db to prohibit corrupted data",
                               level=logging.ERROR)
        self.raw.clear_db()
      else:
        self.update_status_bar("{} created".format(self.raw_db_name))
      self._show_progress(False)
      self._update_raw_status()
      self._set_db_interaction(True)
      self.use_raw()
      for i in ['load', 'pp']:
        t = self._threads.pop(i)
        t.deleteLater()

    @pyqtSlot(bool)
    def _pp(self, b):
      '''Post process slot after load db'''
      if b:
        self._show_progress(False)
        self.update_status_bar("Aborted loading - "
                               "delete db to prohibit corrupted data",
                               level=logging.ERROR)
        self.raw.clear_db()
        self._update_raw_status()
        self._set_db_interaction(True)
        self.use_raw()
        return None
      self.update_status_bar("Post Process DB - This could take awile")
      pp = PostProcessingDB(self.raw, self.entrez,
                            parent_logger_name=self.logger_name)
      pp.finished.connect(self._finish_pp)
      pp.update_prog.connect(self._prog_update)
      pp.update_status.connect(self._status_update)
      self.sig_abort_load.connect(pp._abort)
      # need to store worker too otherwise will be gc'd
      self._threads['pp'] = pp
      pp.start()

    def _abort_load(self):
      '''Abort the load and pp'''
      self.sig_abort_load.emit()

    def _load_raw_database(self):
      '''load raw database from search'''
      search = self.txt_search.text()
      if search.strip() == '':
        self.update_status_bar("Empty search string")
        return None  
      self._set_db_interaction(False)
      self.update_status_bar("Clearing existing DB")
      self.raw.clear_db()
      self._prog_update('Loading Database:', 0, 1)
      self._show_progress(True)
      worker = LoadingDB(parent=self, db=self.raw,
                         entrez=self.entrez,
                         search = search)
      worker.update_prog.connect(self._prog_update)
      worker.update_status.connect(self._status_update)
      worker.finished.connect(self._pp)
      self.sig_abort_load.connect(worker._abort)
      # need to store worker too otherwise will be gc'd
      self._threads['load'] = worker
      worker.start()

