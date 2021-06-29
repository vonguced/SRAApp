from PyQt5 import uic
from PyQt5.QtWidgets import (QWidget, QFileDialog)
from PyQt5.QtCore import Qt
from xlrd import open_workbook
from xlwt import Workbook, easyxf
from logging import WARNING

class Export(QWidget):
  """Widget class for data export"""

  def __init__(self, parent):
    super(Export, self).__init__()
    uic.loadUi('gui/ui/export_gui.ui', self)
    self.setWindowModality(Qt.ApplicationModal)
    self.parent = parent
    self.export_method = self.rad_sra 
    self.export_type = 'NCBI'
    self.rad_asa3p.setText("Export ASA\u00B3P")
    self._connect_events()

  def _connect_events(self):
    '''Connect events of options present in this q widget'''
    self._connect_buttons()
    self._connect_export_methods()
    self._connect_export_types()

  def _connect_buttons(self):
    self.but_cancel.clicked.connect(self.close)
    self.but_export.clicked.connect(self._export)

  def _connect_export_methods(self):
    self.rad_sra.toggled.connect(self.on_clicked_method)
    self.rad_sra.method = self._export_accession
    self.rad_sra_assembly.toggled.connect(self.on_clicked_method)
    self.rad_sra_assembly.method = self._export_accession_assembly
    self.rad_bactopia.toggled.connect(self.on_clicked_method)
    self.rad_bactopia.method = self._export_accession_bactopia
    self.rad_asa3p.toggled.connect(self.on_clicked_method)
    self.rad_asa3p.method = self._export_accession_asa3p

  def _connect_export_types(self):
    self.rad_ncbi.toggled.connect(self.on_clicked_type)
    self.rad_aws.toggled.connect(self.on_clicked_type)
    self.rad_gcp.toggled.connect(self.on_clicked_type)

  def on_clicked_method(self):
    if self.sender().isChecked():
      self.export_method = self.sender()

  def on_clicked_type(self):
    if self.sender().isChecked():
      self.export_type = self.sender().text()

  def _export(self):
    '''Handels export button, checks selection and export the selected'''
    self.export_method.method()
    self.close()

  def _export_helper(self, export_list, ext=".txt"):
    l = self.export_type.lower()
    u = self.export_type
    if u != 'NCBI':
      self.parent.update_status_bar(f"Exporting {u} might not contain "
                                     "all runs present in the DB",
                                      level=WARNING)
    req_res = []
    files = []
    for request, fd_title, fd_default in export_list:
      req_res.append(self.parent.db_in_use.db.get_data(request.format(u=u)))
      file = self._save_file_dialog(sf=fd_title.format(u=u),
                                    default=fd_default.format(l=l),
                                    ext=ext)
      if not file:
        self.parent.logger.warning('Export path not selected')
        return None
      files.append(file)
    return [(r,f) for r,f in zip(req_res, files)]

  def _export_sra_accession(self, req_res, file):
    self.parent.update_status_bar("Writing File: {}".format(file))
    with open(file, 'w') as f:
      f.write('url,filename,md5-checksum\n')
      for res in req_res:
        f.write('{url},{fn},{md5}\n'.format(url=res['url'],
                                              fn=res['f'],
                                              md5=res['md5']))

  def _export_assembly(self, req_res, file):
    self.parent.update_status_bar("Writing File: {}".format(file))
    with open(file, 'w') as f:
      f.write('Assembly_rpt,GenBank,RefSeq,Regions_rpt,Stats_rpt\n')
      for res in req_res:
        f.write('{abl},{gen},{ref},{reg},{sta}\n'.format(
          abl=res['Assembly_rpt'], gen=res['GenBank'], ref=res['RefSeq'],
          reg=res['Regions_rpt'], sta=res['Stats_rpt']))

  def _export_bactopia(self, req_res, file):
    self.parent.update_status_bar("Writing File: {}".format(file))
    with open(file, 'w') as f:
      f.write('\t'.join(['sample','runtype','r1','r2','extra\n']))
      for res in req_res:
        fn = res['fn'].upper()
        if res['nreads'] == "1":
          f.write('\t'.join([f'{fn}','single-end',
                             f'$SRA_HOME/{fn}.fastq.gz','','','\n']))
        else:
          f.write('\t'.join([f'{fn}','paired-end',
                             f'$SRA_HOME/{fn}_1.fastq.gz',
                             f'$SRA_HOME/{fn}_2.fastq.gz','','\n']))

  def _export_asa3p(self, req_res, file):
    #export for asa3p needs an xls file format
    self.parent.update_status_bar("Writing File: {}".format(file))
    wb = ASA3P_config()
    for res in req_res:
      fn = res['fn'].upper()
      if res['platform'] == 'illumina':
        if res['nreads'] == "1":
          wb.add_data_row(f'{fn}', 'single', f'{fn}.fastq.gz')
        else:
          wb.add_data_row(f'{fn}', 'paired-end', f'{fn}_1.fastq.gz','',f'{fn}_2.fastq.gz')
      elif res['platform'] == 'pacbio_smrt':
        pass
      elif res['platform'] == 'oxford_nanopore':
        pass
      else:
        pass
    wb.save(file)

  def _export_accession(self):
    '''Handle export of accession numbers'''
    hl = self._export_helper([("match (s:sra_file) "
                               "where s.semantic_name = 'run' "
                               "return s.filename as f, s.{u}_url as url, "
                               "s.md5 as md5",
                               "Select {u} URL Save File",
                               "sra_{l}_urls")], ".csv")
    if not hl:
      return None
    self.setEnabled(False)
    self._export_sra_accession(*hl[0])
    self.parent.update_status_bar("")
    self.setEnabled(True)

  def _export_accession_assembly(self):
    '''Handle export of assembly and sra accession numbers'''
    hl = self._export_helper([("match (s:sra_file)--(r:run)-"
                               "-(:experiment)--(sa:sample) "
                               "where not (sa)--(:assembly) and "
                               "s.semantic_name = 'run' "
                               "return s.filename as f, "
                               "s.{u}_url as url, s.md5 as md5",
                               "Select {u} URL Save File",
                               "sra_{l}_urls_wo_assembly"),

                              ("match (a:assembly) return "
                               "a.FtpPath_Assembly_rpt as Assembly_rpt, "
                               "a.FtpPath_GenBank as GenBank, "
                               "a.FtpPath_RefSeq as RefSeq, "
                               "a.FtpPath_Regions_rpt as Regions_rpt, "
                               "a.FtpPath_Stats_rpt as Stats_rpt",
                               "Select Assembly URL Save File",
                               "assembly_urls")], ".csv")
    if not hl:
      return None
    self.setEnabled(False)
    self._export_assembly(*hl[1])
    self._export_sra_accession(*hl[0])
    self.parent.update_status_bar("")
    self.setEnabled(True)

  def _export_accession_bactopia(self):
    '''Handle export in bactopia FOFN'''
    #library layout might have the wrong number - nreads is a better option to
    #determine if something is single or paired end
    hl = self._export_helper([("match (r:run)--(e:experiment)--(p:platform) "
                             "where p.type = 'illumina' "
                             "return r.nreads as nreads, r.accession as fn",
                             "Select Bactopia Seve File",
                             "sra_bactopia")], ".txt")
    #Query for hybrid bactopia lines
    # match (p1:platform)--(e1:experiment)--(s:sample)-
    #       -(e2:experiment)--(p2:platform) 
    # where p1.type='illumina' and 
    #       p2.type in ['pacbio_smrt', 'oxford_nanopore'] 
    # match (e1)--(r1:run) match (e2)--(r2:run) 
    # return r1.accession as short_reads, 
    #        r2.accession as long_reads, 
    #        s.accession as fn
    # This is not included as only 19 samples in ~1600 experiments are affected
    # it could create more questions especially because of combinatorics some 
    # samples could have multiple short and multiple long read experiments 
    # -> which to combine?
    if not hl:
      return None
    self.setEnabled(False)
    self._export_bactopia(*hl[0])
    self.parent.update_status_bar("")
    self.setEnabled(True)
    return None

  def _export_accession_asa3p(self):
    '''Handle export as asa3p config file'''
    #library layout might have the wrong number - nreads is a better option to
    #determine if something is single or paired end
    hl = self._export_helper([("match (r:run)--(e:experiment)--(p:platform) "
                             "return r.nreads as nreads, r.accession as fn, "
                             "p.type as platform",
                             "Select ASA\u00B3P Save File",
                             "config")], ".xls")
    #Hybrides are not includes -> see _export_accession_bactopia
    if not hl:
      return None
    self.setEnabled(False)
    self._export_asa3p(*hl[0])
    self.parent.update_status_bar("")
    self.setEnabled(True)
    return None

  def _save_file_dialog(self, sf="Select Save File",
                        default="sra_ncbi_urls",
                        ext=".txt"):
    '''Dialog to select save path'''
    options = QFileDialog.Options()
    options |= QFileDialog.DontUseNativeDialog
    if ext == ".xls":
      des = f"Excel File (*{ext})"
    else:
      des = f"Text File (*{ext})"
    default = self._add_file_extension(default, ext)
    file_name, _ = QFileDialog.getSaveFileName(self,
      sf, default,
      des, options=options)
    file_name = self._add_file_extension(file_name, ext)
    if not file_name:
      return ""
    return file_name

  def _add_file_extension(self, fn, ex):
    '''Adds a file extension to a filename if missing'''
    l = len(ex)
    if fn[-l:] != ex:
      fn += ex
    return fn

class ASA3P_config(Workbook):
  """Class to handle the excel methods
     for the asa3p config file
     This class inits a basic config file
     and provides classes to save this file
     with a certain path and to add data rows"""

  title_12 = easyxf('font: bold 1, color black, height 240;')
  title_table_12 = easyxf('font: bold 1, color black, height 240;\
                     borders: top_color black, bottom_color black, right_color black, left_color black,\
                     left thin, right thin, top thin, bottom thin;\
                     pattern: pattern solid, fore_color white;')
  title_table = easyxf('font: bold 1, color black, height 200;\
                     borders: top_color black, bottom_color black, right_color black, left_color black,\
                     left thin, right thin, top thin, bottom thin;\
                     pattern: pattern solid, fore_color white;')
  table = easyxf('font: bold off, color black, height 200;\
                     borders: top_color black, bottom_color black, right_color black, left_color black,\
                     left thin, right thin, top thin, bottom thin;\
                     pattern: pattern solid, fore_color white;')
  wrap = easyxf('alignment: wrap True')

  def __init__(self):
    super(ASA3P_config, self).__init__()
    self.template = open_workbook('./gui/widgets/asa3p_config.xls')
    self.project = self.add_sheet('Project', cell_overwrite_ok=True)
    self.strains = self.add_sheet('Strains', cell_overwrite_ok=True)
    self.title12_style = self.add_style(self.title_12)
    self.title12_table_style = self.add_style(self.title_table_12)
    self.title_table_style = self.add_style(self.title_table)
    self.table_style = self.add_style(self.table)
    self.wrap_style = self.add_style(self.wrap)
    self._init_project()
    self._init_strains()
    self.current_row = 1
    self.input_types = ['single','paired-end','mate-pairs','pacbio-rs2',
                        'pacbio-sequel','nanopore','nanopore-pe','contigs'
                        'contigs-ordered','genome']

  def _set_style_idx(self, sheet, row, col, style_idx):
    sheet.get_rows()[row]._Row__cells[col].xf_idx = style_idx

  def _init_project(self):
    #copy from template
    tmp_pro = self.template.sheets()[0]
    for row in range(15):
      data = tmp_pro.row_values(row)
      for col in range(len(data)):
        self.project.write(row,col,data[col])
    #format sheet
    for r in [15,16]:
      for c in [0,1]:
        self.project.write(r,c,'')
    for r in [1,2,3,7,8,9,13,14,15,16]:
      for c in range(2):
        self._set_style_idx(self.project, r, c, self.table_style)
    for r, c in [(0,0),(6,0),(12,0),(0,3),(0,4)]:
      self._set_style_idx(self.project, r, c, self.title12_style)
    self.project.merge(0,0,0,1)
    self.project.merge(6,6,0,1)
    self.project.merge(12,12,0,1)
    self.project.merge(3,4,3,3)
    self._set_style_idx(self.project, 3, 3, self.wrap_style)
    self.project.merge(13,18,3,3)
    self._set_style_idx(self.project, 13, 3, self.wrap_style)

  def _init_strains(self):
    #copy from template
    tmp_str = self.template.sheets()[1]
    for row in range(7):
      data = tmp_str.row_values(row)
      for col in range(len(data)):
        self.strains.write(row,col,data[col])
    #format sheet
    for r in range(1,7):
      for c in range(8,10):
        self._set_style_idx(self.strains, r, c, self.table_style)
    for c in range(6):
      self._set_style_idx(self.strains, 0, c, self.title12_style)
    for c in range(8,10):
      self._set_style_idx(self.strains, 0, c, self.title12_table_style)
    for r in range(1,7):
      self._set_style_idx(self.strains, r, 7, self.title_table_style)

  def add_data_row(self, strain, input_type, file1, 
                   species="", file2="", file3=""):
    self.strains.write(self.current_row, 0, species)
    self.strains.write(self.current_row, 1, strain)
    self.strains.write(self.current_row, 2, input_type)
    self.strains.write(self.current_row, 3, file1)
    self.strains.write(self.current_row, 4, file2)
    self.strains.write(self.current_row, 5, file3)
    self.current_row += 1
