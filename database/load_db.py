"""Loading and Postprocessing Neo4j DB from File

This module contains all the classes needed to load and postprocess
the ncbi experiment package xml data into a neo4j database.
"""

import xml.etree.ElementTree as ET
from database.xml_keywords import *
from database.helper_functions import *
import logging
from functools import partial
import threading
import time
import queue

from PyQt5.QtCore import (QObject, QRunnable, QThread,
                          QThreadPool, pyqtSignal, pyqtSlot)

class LoadingDB(QThread):
    '''
    Class to load xml into a neo4j db

    Args:
        db (SRAMetadataDB): Database to load data into
        search (str): Search string for NCBI
        
        *args and **kwargs are not handled in this class they are
        passed on to super

    Attributes:
        search: NCBI search string
        db: Neo4j Database provieded by args

    Signals:
        finished(bool): Signals if async load is finished
        update_status(str): Status update of current task
        update_prog(str, int, int): Progress of task str done int of int
    '''

    finished = pyqtSignal(bool)
    update_prog = pyqtSignal(str, int, int)
    update_status = pyqtSignal(str)

    def __init__(self, parent, db, entrez, search, *args, **kwargs):
        super(LoadingDB, self).__init__(*args, **kwargs)
        self.parent = parent
        self.logger_name = '{}.LoadingDB'.format(self.parent.logger_name)
        self.logger = logging.getLogger(self.logger_name)
        self.db = db
        self.ez = entrez
        self.search = search
        self.cql_has_reads = False
        self.abort = False

    @pyqtSlot(int, int)
    def _handle_db_signal(self, i, m):
        self.update_prog.emit('Loading Database:', i, m)

    @pyqtSlot(int, int)
    def _handle_producer_signal(self, i, m):
        self.update_status.emit("Producer {}/{} finished".format(i, m))

    @pyqtSlot(int, int)
    def _handle_parser_signal(self, i, m):
        self.update_status.emit("Parser {}/{} finished".format(i, m))

    @pyqtSlot()
    def _abort(self):
        if hasattr(self, 'asy'):
            self.asy._abort()
        self.abort = True

    def cql_of_experiment_package(self, exp_pkg, n_exp_pkg):
        '''Create a cypher from an experiment package xml'''
        self.n = n_exp_pkg
        cql = [self._cql_of_experiment(exp_pkg.find(xml_EXPERIMENT))]
        cql.append(self._cql_of_submission(exp_pkg.find(xml_SUBMISSION)))
        cql.append(self._cql_of_organization(exp_pkg.find(xml_Organization)))
        cql.append(self._cql_of_study(exp_pkg.find(xml_STUDY)))
        sams = exp_pkg.findall(xml_SAMPLE)
        pool = exp_pkg.find(xml_Pool)
        # pool is not in every dataset
        if pool:
            if len(sams) != len(pool.findall(xml_Member)):
                self.logger.error("Error: Pool and samples do not match!")
        cql.append(self._cql_of_samples(sams))
        if pool:
            cql.append(self._cql_of_pool(pool))
        cql.append(self._cql_of_runs(exp_pkg.find(xml_RUN_SET)))
        return ' '.join(cql)

    def run(self):
        '''start the async load of database'''
        self.async_load_sra_from_query(self.search)
        self.finished.emit(self.asy.abort | self.asy.error)

    def async_load_sra_from_query(self, query,
                                  retmax=150, batch = 150):
        '''Create async class and start it'''
        self.asy = AsyncEntrez(self, fun_initial=self._esearch_initial,
                          fun_id_producer=self._esearch_sra_ids,
                          fun_data_parser=self._esearch_sra_data_getter,
                          fun_db_consumer=self._load_sra_data,
                          retmax = retmax, batch = batch,
                          start_id = 0)
        self.asy.db_signal.connect(self._handle_db_signal)
        self.asy.parser_signal.connect(self._handle_parser_signal)
        self.asy.producer_signal.connect(self._handle_producer_signal)
        self.asy.async_from_query(query)
         
    def _esearch_initial(self, query):
        '''Return initial esearch result - needed for count'''
        return self.ez.read(self.ez.esearch(db='sra', term=query))

    def _esearch_sra_ids(self, query, retstart, retmax):
        '''Get sra ids from esearch'''
        return self.ez.read(self.ez.esearch(db='sra', term=query,
                                            retstart=retstart,
                                            retmax=retmax, rettype='full',
                                            retmode='text'))

    def _esearch_sra_data_getter(self, ids):
        '''Get sra xml data from esearch ids'''
        xml = self.ez.efetch(db="sra", id=ids, report="fullXML").read()
        return ET.fromstring(xml)

    def _load_sra_data(self, exp_pkg, i):
        '''Function to load dataset into the database'''
        #let it run unsafe as errors will get catched by AsyncEntrez
        self.db.unsafe_run_cql(self.cql_of_experiment_package(exp_pkg, i))

    def _get_instrument(self, experiment):
        '''Get the instrument from the xml'''
        platform = experiment.find(xml_PLATFORM)
        inst_type = platform[0].tag
        inst_model = platform[0][0].text
        return escape_attrib({"type": inst_type, "model": inst_model})

    def _get_design(self, design):
        '''Get the desing from the xml'''
        des = {"exp_pkg":self.n}
        des["description"] = design.find(xml_DESIGN_DESCRIPTION).text or ""
        return escape_attrib(des)

    def _get_library(self, design):
        '''Get the library from the xml'''
        lib = {"exp_pkg":self.n}
        ld = design.find(xml_LIBRARY_DESCRIPTOR)
        library = [(i.tag, i.text) for i in ld 
                   if not i.tag == xml_LIBRARY_LAYOUT]
        for tag, text in library:
            lib[tag] = text or ""
        lib[xml_LIBRARY_LAYOUT] = ld.find(xml_LIBRARY_LAYOUT)[0].tag
        return escape_attrib(lib)

    def _get_experiment(self, experiment):
        '''Get the experiment from the xml'''
        exp = experiment.attrib
        exp['exp_pkg'] = self.n
        exp["title"] = experiment.find(xml_TITLE).text or ""
        return escape_attrib(exp)

    def _get_submission(self, submission):
        '''Get the submission from the xml'''
        return escape_attrib(submission.attrib)

    def _get_organization(self, organization):
        '''Get the organization from the xml'''
        org = organization.attrib
        org = merge_dict(org, organization.find(xml_Name).attrib)
        if organization.find(xml_Contact):
            org = merge_dict(org, organization.find(xml_Contact).attrib)
        org[xml_Name] = organization.find(xml_Name).text
        return escape_attrib(org)

    def _get_study(self, study):
        '''Get the study from the xml'''
        stu = study.attrib
        for study_info in study.find(xml_DESCRIPTOR):
            if not study_info.text:
                stu = merge_dict(stu, study_info.attrib)
            else:
                stu[study_info.tag] = study_info.text
        if study.find(xml_STUDY_LINKS):
            stu = merge_dict(stu, self._get_study_links(
                                  study.find(xml_STUDY_LINKS)))
        return escape_attrib(stu)

    def _get_study_links(self, study_links):
        '''Get the study links from the xml'''
        stu_l = {}
        links = set()
        for study_link in study_links:
            i = 2
            link = study_link[0]
            base_tag = link.tag
            tag = base_tag
            while tag in links:
                tag = base_tag + "%s" % i
                i += 1
            links.add(tag)
            for info in link:
                if info.text:
                    stu_l[tag + "_" + info.tag] = info.text
        return stu_l

    def _get_sample(self, sample):
        '''Get the sample from the xml'''
        sam = sample.attrib
        ext = sample.find(xml_IDENTIFIERS+'/'+xml_EXTERNAL_ID)
        sam = merge_dict(sam, ext.attrib)
        sam[ext.tag] = ext.text
        if sample.find(xml_TITLE):
            sam[xml_TITLE] = sample.find(xml_TITLE).text
        else:
            sam[xml_TITLE] = ""
        sam[xml_TAXON_ID] = sample.find(xml_SAMPLE_NAME+'/'+xml_TAXON_ID).text
        sam[xml_SCIENTIFIC_NAME] = sample.find(xml_SAMPLE_NAME+'/'+
                                               xml_SCIENTIFIC_NAME).text
        if sample.find(xml_DESCRIPTION):
            sam[xml_DESCRIPTION] = sample.find(xml_DESCRIPTION).text
        return escape_attrib(sam)

    def _get_member(self, member):
        '''Get the member from the xml'''
        mem = {"exp_pkg":self.n}
        mem["spots"] = member.attrib[xml_spots]
        mem["bases"] = member.attrib[xml_bases]
        mem["accession"] = member.attrib[xml_accession]
        return escape_attrib(mem)

    def _get_attributes(self, dom, dom_str):
        '''Get the attributes helper from the xml'''
        att = {}
        if not dom.find(dom_str):
            return att
        for a in dom.find(dom_str):
            att[a.find(xml_TAG).text] = a.find(xml_VALUE).text or ""
        return escape_attrib(att)

    def _get_run_attributes(self, run):
        '''Get the run attributes from the xml'''
        att = self._get_attributes(run, xml_RUN_ATTRIBUTES)
        att["exp_pkg"] = self.n
        return att

    def _get_sample_attributes(self, sample):
        '''Get the sample attributes from the xml'''
        return self._get_attributes(sample, xml_SAMPLE_ATTRIBUTES)

    def _get_run(self, run_dom):
        '''Get the run from the xml'''
        run = run_dom.attrib
        run["exp_pkg"] = self.n
        return escape_attrib(run)

    def _get_SRA_files(self, run):
        '''Get the SRA file links from the xml'''
        sra_files = run.find(xml_SRAFiles)
        if not sra_files:
            return []
        return [self._get_SRA_file(sra_file, set_exp_pkg=False)
                for sra_file in sra_files]

    def _get_SRA_file(self, sra_file, set_exp_pkg=False):
        '''Get the file link helper from the xml'''
        f = sra_file.attrib
        if set_exp_pkg:
            f["exp_pkg"] = self.n
        for alternative in sra_file:
            att = alternative.attrib
            org = att.pop('org')
            new = dict()
            for k, v in att.items():
                new[f"{org}_{k}"] = v
            f = merge_dict(f, new)
        return escape_attrib(f)

    def _get_files(self, files):
        '''Get the file link helper from the xml'''
        if not files:
            return []
        f = files.attrib
        for alternative in files:
            f = merge_dict(f, alternative.attrib)
        return escape_attrib(f)

    def _get_cloud_files(self, run):
        '''Get the cloud file links from the xml'''
        cloud_files = run.find(xml_CloudFiles)
        if not cloud_files:
            return []
        return [self._get_SRA_file(cloud_file) for cloud_file in cloud_files]

    def _get_statistics(self, run):
        '''Get the statistics from the xml'''
        statistics = run.find(xml_Statistics)
        if not statistics:
            return []
        sta = statistics.attrib
        if not statistics.findall(xml_Read):
            return sta
        sta['reads'] = [read.attrib for read in statistics.findall(xml_Read)]
        return sta

    def _get_spot_descriptor(self, des):
        '''Get the spot descriptor from the xml'''
        spd = {"exp_pkg":self.n}
        spot_decode = des.find(xml_SPOT_DESCRIPTOR+'/'+xml_SPOT_DECODE_SPEC)
        if not spot_decode:
            return {}
        for sd in spot_decode:
            if sd.tag != xml_READ_SPEC:
                spd[sd.tag] = sd.text
        return escape_attrib(spd)

    def _get_read_specs(self, des):
        '''Get the read specifications from the xml'''
        spot_decode = des.find(xml_SPOT_DESCRIPTOR+'/'+xml_SPOT_DECODE_SPEC)
        if not spot_decode:
            return []
        return [self._get_read_spec(read_spec) for read_spec
                in spot_decode.findall(xml_READ_SPEC)]

    def _get_base_calls(self, basecall):
        '''Get the basecalls from the xml'''
        bc = basecall.attrib
        bc["exp_pkg"] = self.n
        bc['basecall'] = basecall.text
        return bc

    def _get_read_spec(self, read_spec):
        '''Get the read specificartion from the xml'''
        rs = {"exp_pkg":self.n}
        for spec in read_spec:
            if spec.tag == xml_EXPECTED_BASECALL_TABLE:
                rs['basecalls'] = [self._get_base_calls(basecall) 
                                   for basecall in spec]
            else:
                if not spec.text:
                    rs = merge_dict(rs, spec.attrib)
                else:
                    rs[spec.tag] = spec.text
        return escape_attrib(rs)

    def _get_bases(self, run):
        '''Get the bases from the xml'''
        bases = run.find(xml_Bases)
        if not bases:
            return {}
        bas = bases.attrib
        bas["exp_pkg"] = self.n
        for base in bases:
            bas[base.attrib[xml_value]] = base.attrib[xml_count]
        return bas

    def _cql_of_reads(self, reads):
        '''Create a cypher for the reads'''
        cql = []
        for rd in reads:
            bcs = rd.pop('basecalls', [])
            cql.append(cql_create("read", rd, "rd%s" % rd[xml_READ_INDEX]))
            cql.append(cql_relation("des", "hasRead", 
                                    "rd%s" % rd[xml_READ_INDEX]))
            for i, bc in enumerate(bcs):
                cql.append(cql_create("basecall", bc,
                                      "bc%s%s" % (rd[xml_READ_INDEX], i)))
                cql.append(cql_relation("rd%s" % rd[xml_READ_INDEX], 
                                        "hasBasecall", 
                                        "bc%s%s" % (rd[xml_READ_INDEX], i)))
        return ' '.join(cql)

    def _cql_of_experiment(self, exp):
        '''Create a cypher for the experiment'''
        des = exp.find(xml_DESIGN)
        cql = [cql_create("design", self._get_design(des), "des")]
        cql.append(cql_create("library", self._get_library(des), "lib"))
        cql.append(cql_relation("des", "usingLibrary", "lib"))
        spd = self._get_spot_descriptor(des)
        if spd:
            cql.append(cql_create("spot_descriptor", spd, "spd"))
            cql.append(cql_relation("des", "hasSpotDescriptor", "spd"))
        reads = self._get_read_specs(des)
        if not reads: 
            self.cql_has_reads = False
        else:
            self.cql_has_reads = True
            cql.append(self._cql_of_reads(reads))
        cql.append(cql_create("platform", self._get_instrument(exp), "inst",
                              merge=True))
        cql.append(cql_create("experiment", self._get_experiment(exp),
                              "exp"))
        cql.append(cql_relation("exp", "hasDesign", "des"))
        cql.append(cql_relation("exp", "usingInstrument", "inst"))
        return ' '.join(cql)

    def _cql_of_submission(self, sub):
        '''Create a cypher for the submission'''
        cql = [cql_create("submission", self._get_submission(sub), "sub",
                          merge=True)]
        cql.append(cql_relation("exp", "submittedBy", "sub"))
        return ' '.join(cql)

    def _cql_of_organization(self, org):
        '''Create a cypher for the organization'''
        cql = [cql_create("organization", self._get_organization(org), "org",
                          merge=True)]
        return ' '.join(cql)

    def _cql_of_study(self, stu):
        '''Create a cypher for the study'''
        cql = [cql_create("study", self._get_study(stu), "stu", merge=True)]
        cql.append(cql_relation("stu", "carriedOutBy", "org", merge=True))
        cql.append(cql_relation("exp", "doneIn", "stu"))
        return ' '.join(cql)

    def _cql_of_samples(self, sams):
        '''Create a cypher for the samples'''
        cql = []
        for i, sam in enumerate(sams):
            cql.append(cql_create("sample", self._get_sample(sam),
                                  "sam%s" % i, merge=True))
            cql.append(cql_relation("sam%s" % i, "submittedBy", "sub",
                                    merge=True))
            cql.append(cql_relation("sam%s" % i, "usedIn", "exp"))
            cql.append(cql_relation("sam%s" % i, "usedIn", "stu", merge=True))
            att = self._get_sample_attributes(sam)
            if att:
                cql.append(cql_create("sample_attrib", att, "sam_att%s" % i,
                                      merge=True))
                cql.append(cql_relation("sam%s" % i, "hasSampleAttribute",
                                        "sam_att%s" % i, merge=True))
        return ' '.join(cql)

    def _cql_of_pool(self, pool):
        '''Create a cypher for the pool data'''
        cql = []
        for i, mem in enumerate(pool.findall(xml_Member)):
            cql.append(cql_create("member", self._get_member(mem),
                                  "mem%s" % i, merge=True))
            # check later if accessions match!!! - ToDo
            cql.append(cql_relation("sam%s" % i, "hasPoolData",
                                    "mem%s" % i))
        return ' '.join(cql)

    def _cql_of_read_statistics(self, reads, run_var, empty_read=False):
        '''Create a cypher for the statistics'''
        cql = []
        for read in reads:
            j = read['index']
            s = "rd%s" % j
            if empty_read:
                s = "rd"
            cql.append(cql_relation(run_var, "readStatistics",
                                    s, merge=False,
                                    attributes=read))
        return ' '.join(cql)

    def _cql_of_runs(self, runs):
        '''Create a cypher for the runs'''
        cql = []
        for i, run in enumerate(runs):
            sta = self._get_statistics(run)
            r = self._get_run(run)
            reads = None
            if sta:
                reads = sta.pop('reads', None)
                r = merge_dict(r, sta)
            cql.append(cql_create("run", r, "run%s" % i))
            if reads:
                if not self.cql_has_reads:
                    if i < 1:
                        cql.append(cql_create("read", {'exp_pkg':self.n}, 
                                              "rd"))
                    cql.append(self._cql_of_read_statistics(reads, 
                                      "run%s" % i, empty_read=True))
                else:
                    cql.append(self._cql_of_read_statistics(reads, 
                                                             "run%s" % i))
            cql.append(cql_relation("exp", "hasRun", "run%s" % i))
            pool = run.find('Pool')
            if pool:
                for j, mem in enumerate(pool.findall(xml_Member)):
                    cql.append(cql_create("member", self._get_member(mem),
                                          "mem%s%s" % (i, j), merge=True))
                    cql.append(cql_relation("run%s" % i, "hasPoolData",
                                            "mem%s%s" % (i, j)))
            run_att = self._get_run_attributes(run)
            if run_att:
                cql.append(cql_create("run_attrib", run_att,
                                      "run_att%s" % i))
                cql.append(cql_relation("run%s" % i, "hasRunAttribute",
                                        "run_att%s" % i))
            sra_files = self._get_SRA_files(run)
            for j, sra_file in enumerate(sra_files):
                cql.append(cql_create("sra_file", sra_file,
                                      "sra_f%s%s" % (i, j)))
                cql.append(cql_relation("run%s" % i, "hasSRAFile",
                                        "sra_f%s%s" % (i, j)))
            cloud_files = self._get_cloud_files(run)
            for j, cloud_file in enumerate(cloud_files):
                cql.append(cql_create("cloud_file", cloud_file,
                                      "cloud_f%s%s" % (i, j), merge=True))
                cql.append(cql_relation("run%s" % i, "hasCloudFile",
                                        "cloud_f%s%s" % (i, j)))
            bases = self._get_bases(run)
            if bases:
                cql.append(cql_create("bases", bases, "bas%s" % i))
                cql.append(cql_relation("run%s" % i, "hasBases",
                                        "bas%s" % i))
        return ' '.join(cql)

class PostProcessingDB(QThread):
  '''
    Manages the postprocessing of the data after they got added to neo4j

    Args:
        db (SRAMetadataDB): Neo4j DB to postprocess
        entrez (Entrez): Entrez (NCBI) connection with set email

    Attributes:
        db (SRAMetadataDB): Database from args
        ez (Entrez): Entrez from args
        delete_lsit: List of values to delete form db
        similar_list: list of properties to replace in db
        dates_to_fix: list of dates in db which should be fixed

    Signals:
        finished(bool): Signals if async post process is finished
        update_status(str): Status update of current task
        update_prog(str, int, int): Progress of task str done int of int
    '''

  finished = pyqtSignal(bool)
  update_status = pyqtSignal(str)
  update_prog = pyqtSignal(str, int, int)

  def __init__(self, db, entrez, parent_logger_name=""):
    super(PostProcessingDB, self).__init__()
    self.logger_name = '{}.PostProcessingDB'.format(parent_logger_name)
    self.logger = logging.getLogger(self.logger_name)
    self.db = db
    self.ez = entrez
    self.error = False
    self.delete_list = ['missing','not applicable', 'n/a', 'not available',
                         'na', 'not collected', 'unknown']
    self.similar_list = [
        ('sample_attrib', '`isolation-source`', 'isolation_source'),
        ('sample_attrib', '`isolation source`', 'isolation_source'),
        ('sample_attrib', 'STRAIN', 'strain'),
        ('sample_attrib', 'Strain', 'strain'),
        ('sample_attrib', '`collection date`', 'collection_date'),
        ('sample_attrib', '`culture-collection`', 'culture_collection'),
        ('sample_attrib', 'environment_biome', 'env_biome'),
        ('sample_attrib', 'biome', 'env_biome'),
        ('sample_attrib', 'material', 'env_material'),
        ('sample_attrib', '`Sample Name`', 'sample_name'),
        ('sample_attrib', 'Isolate', 'isolate')]
    self.dates_to_fix = {'sample_attrib':['collection_date'],
                         'assembly':['SubmissionDate', 'SeqReleaseDate',
                                     'AsmUpdateDate', 'AsmReleaseDate_RefSeq',
                                     'AsmReleaseDate_GenBank',
                                     'LastUpdateDate'],
                         'run':['published'],
                         'sra_file':['date']}

  @pyqtSlot(int, int)
  def _handle_db_signal(self, i, m):
    self.update_prog.emit('PostProcessingDB:', i, m)

  @pyqtSlot(int, int)
  def _handle_producer_signal(self, i, m):
    self.update_status.emit("Producer {}/{} finished".format(i, m))

  @pyqtSlot(int, int)
  def _handle_parser_signal(self, i, m):
    self.update_status.emit("Parser {}/{} finished".format(i, m))

  @pyqtSlot()
  def _abort(self):
    if hasattr(self, 'asy'):
      self.asy._abort()
      self.abort = True

  def check_db_status(self):
    '''Check database for corruption'''
    if not self.check_relationships():
      return False
    #dont check for assembly as there might not be any
    if not self.check_integers():
      return False
    if not self.check_gc_ratios():
      return False
    #ignore lowercase - hard and long to check and
    #just convinient for lists
    #should be ok if all things below are ok as well
    if not self.check_delete_unknowns():
      return False
    if not self.check_replace_similar():
      return False
    if not self.check_geo_name():
      return False
    #ignore dates - hard and long to check and
    #just convinient for lists
    return True

  def check_relationships(self):
    '''check if needed relationships are set'''
    cql = ("match (rd:read), (des:design) "
           "where not (des)--(rd) and des.exp_pkg = rd.exp_pkg "
           "return count(des) as c")
    if self.db.get_data(cql)[0]['c'] > 0:
      return False
    cql = ("match (rd:read), (r:run) "
           "where not (r)--(rd) and r.exp_pkg = rd.exp_pkg "
           "return count(r) as c")
    if self.db.get_data(cql)[0]['c'] > 0:
      return False
    return True

  def check_integers(self):
    '''Check if needed integers in db are set'''
    i = []
    cqls = [("match (r:bases) return r.total_bases, "
                "r.A, r.C, r.T, r.G, r.N, r.count")]
    cqls.append("match (n) return n.exp_pkg")
    cqls.append("match (n:assembly_stats) return n.value")
    for cql in cqls:
      recs = self.db.get_data(cql)
      for rec in recs:
        i += rec.values()
    return all([isinstance(j, int) for j in i if j])

  def check_gc_ratios(self):
    '''check if gc ratios are set'''
    cql = "match (n:bases) where not exists(n.GC_Ratio) return count(n) as c"
    if self.db.get_data(cql)[0]['c'] > 0:
      return False
    return True

  def check_delete_unknowns(self):
    '''check if unknowns are deleted from db'''
    del_list = list2str(self.delete_list)
    cql = ("MATCH (n) "
           f"WITH n, [x IN keys(n) WHERE n[x] in {del_list}] as props "
           "unwind props as p return count(n[p]) as c")
    if self.db.get_data(cql)[0]['c'] > 0:
      return False
    return True

  def check_replace_similar(self):
    '''check if all similar props are replaced in db'''
    for att, old_prop, new_prop in self.similar_list:
      cql = f"MATCH (n:{att}) where exists(n.{old_prop}) return count(n) as c"
      if self.db.get_data(cql)[0]['c'] > 0:
        return False
    return True

  def check_geo_name(self):
    '''check if geo names are set in db'''
    cql = ("MATCH (n:sample_attrib) "
           "where apoc.text.indexOf(n.geo_loc_name,':') in [-1, 0] "
           "return count(n.geo_loc_name) as c")
    if self.db.get_data(cql)[0]['c'] > 0:
      return False
    return True

  def run(self):
    '''Post process DB - contains missing relationships, 
       set integer, set gc ratio and set assembly data'''
    s = 'PostProcessing: '
    try:
        self.update_status.emit(s+'Create missing relationships')
        self.create_missing_relationships()
        self.update_status.emit(s+'Set assembly data')
        self.set_assembly_data()
        self.update_status.emit(s+'Set integers')
        self.set_integers()
        self.update_status.emit(s+'Set gc-ratios')
        self.set_gc_ratio()
        self.update_status.emit(s+'Set lowercase')
        self.set_lowercase()
        self.update_status.emit(s+"Delete 'unknown' values")
        self.delete_unknowns()
        self.update_status.emit(s+"Replace similar properties")
        self.replace_similar()
        self.update_status.emit(s+"Fix geo location name")
        self.fix_geo_name()
        self.update_status.emit(s+"Clean dates")
        self.clean_dates()
        self.finished.emit(True)
    except Exception as exc:
        self.logger.error('PostProcessing had error: {}'.format(exc))
        self.finished.emit(False)

  def clean_dates(self, batchsize=20000):
    '''Function to clean the dates to a yyyy-mm-dd format'''
    cd = CleanDate(parent=self)
    #attribs need to be hardcoded in cypher
    #-> loop over keys (attribs) then handle
    #   all props of the same attrib at once
    for attrib, props in self.dates_to_fix.items():
        cql_cleaned = ("with $batch as batch "
                       "unwind batch as record "
                       f"match (s:{attrib}) "
                       "where id(s) = record.id "
                       "CALL apoc.create.setProperty(s, record.prop, "
                                                    "record.date) "
                       "YIELD node RETURN node")
        cql_missing = ("with $batch as batch "
                       "unwind batch as record "
                       f"match (s:{attrib}) "
                       "where id(s) = record.id "
                       "CALL apoc.create.removeProperties(s, [record.prop]) "
                       "YIELD node return node")
        cleaned = []
        missing = []
        for prop in props:
            cql_get = (f"match (s:{attrib}) "
                       f"where exists(s.{prop}) "
                       f"return ID(s) as id, s.{prop} as date")
            records = self.db.get_data(cql_get)
            for record in records:
                d = dict(record)
                d['prop'] = prop
                clean = cd.safe_fix_date(d['date'])
                if clean == 'unknown':
                    missing.append(d)
                else:
                    d['date'] = clean
                    cleaned.append(d)
        for b in batch(missing, batchsize):
            self.db.batch_run_cql(cql_missing, batch=b)
        for b in batch(cleaned, batchsize):
            self.db.batch_run_cql(cql_cleaned, batch=b)

  def fix_geo_name(self):
    '''Fix the geological names to match format country:location'''
    cqls = []
    #remove trailing whithespaces and remove whitespaces around :
    cqls.append("MATCH (n:sample_attrib) where exists(n.geo_loc_name) "
                "set n.geo_loc_name = "
                "trim(apoc.text.replace(n.geo_loc_name, ' *: *', ':'))")
    #set geo_loc:unknown if : does not exist
    cqls.append("MATCH (n:sample_attrib) "
                "where apoc.text.indexOf(n.geo_loc_name,':') = -1 "
                "set n.geo_loc_name = n.geo_loc_name+':unknown'")
    #set unknown:geo_loc if : is first symbol
    cqls.append("MATCH (n:sample_attrib) "
                "where apoc.text.indexOf(n.geo_loc_name,':') = 0 "
                "set n.geo_loc_name = 'unknown:'+n.geo_loc_name")
    #set unknown:unknown if the property is set but empty
    cqls.append("MATCH (n:sample_attrib) where n.geo_loc_name = '' "
                "SET n.geo_loc_name = 'unknown:unknown'")
    for cql in cqls:
        self.db.unsafe_run_cql(cql)

  def set_integers(self):
    '''Set specific attributes as integers (total bases)'''
    self.logger.info("Set specific stirngs to integers")
    cqls = []
    for i in ['total_bases', 'A', 'C', 'T', 'G', 'N', 'count']:
        cqls.append(f"match (r:bases) SET r.{i} = "
                    f"apoc.convert.toInteger(r.{i})")
    cqls.append("match (n) set n.exp_pkg = "
                "apoc.convert.toInteger(n.exp_pkg)")
    cqls.append("match (n:assembly_stats) set n.value = "
                "apoc.convert.toInteger(n.value)")
    for cql in cqls:
        self.db.unsafe_run_cql(cql)
  
  def replace_similar(self):
    '''Function to replace similar properties by one common name'''
    for attrib, old_prop, new_prop in self.similar_list:
        cql = (f"match (n:{attrib}) where n.{old_prop} =~ '.*' "
               f"set n.{new_prop} = n.{old_prop} "
               f"remove n.{old_prop}")
        self.db.unsafe_run_cql(cql)

  def set_lowercase(self):
    '''Set all values in db to lowercase exept urls'''
    self.logger.info("Set all values to lowercase")
    #https://stackoverflow.com/questions/44719470/
    #convert-all-values-of-all-properties-to-lower-case-in-neo4j
    cql = ("MATCH (n) "
    	   "WHERE NOT n:sra_file AND NOT n:cloud_file "
    	   "WITH n, [x IN keys(n) WHERE n[x] =~ '.*'] as props "
           "UNWIND props as p "
           "CALL apoc.create.setProperty(n, p, toLower(n[p])) YIELD node "
           "RETURN count(node)")
    self.db.unsafe_run_cql(cql)

  def delete_unknowns(self):
    '''Delete all unknown values in db'''
    self.logger.info("delete 'unknown' values")
    del_list = list2str(self.delete_list)
    #adapdet from set_lowercase
    cql = ("MATCH (n) "
           f"WITH n, [x IN keys(n) WHERE n[x] in {del_list}] as props "
           "CALL apoc.create.removeProperties(n, props) "
           "YIELD node RETURN count(node)")
    self.db.unsafe_run_cql(cql)

  def set_gc_ratio(self):
    '''Calculate and set the gc ratio'''
    self.logger.info("Calculate the gc ratio")
    cql_gc = ("match (n:bases) set n.GC_Ratio = "
              "(toFloat(n.G)+toFloat(n.C))/toFloat(n.count)")
    self.db.unsafe_run_cql(cql_gc)

  def create_missing_relationships(self):
    '''Creat the missing relationships between design and run'''
    self.logger.info("Create missing relationships")
    cql = ("match (rd:read), (des:design) "
           "where not (des)--(rd) and des.exp_pkg = rd.exp_pkg "
           "create (des)-[:hasRead]->(rd)")
    self.db.unsafe_run_cql(cql)
    cql = ("match (rd:read), (r:run) "
           "where not (r)--(rd) and r.exp_pkg = rd.exp_pkg "
           "create (r)-[:readStatistics]->(rd)")
    self.db.unsafe_run_cql(cql)

  def set_assembly_data(self):
    '''Fetch assembly metadata from ncbi if they exist (asynchron for speed)'''
    self.logger.info("Fetch and set assembly metadata")
    samples = self._get_sample_ids()
    query = '('+' OR '.join(samples)+') AND (latest[filter])'
    self._async_esearch(query, retmax=200, batch = 100)

  def _get_sample_ids(self):
    '''Get all sample ids to fetch data from'''
    sams = self.db.get_data('match (s:sample) return s.EXTERNAL_ID as ex_id')
    return [sam['ex_id'] for sam in sams]

  def _esearch_assembly_ids(self, query, retstart, retmax):
    '''Get assembly ids from esearch'''
    return self.ez.read(self.ez.esearch(db='assembly', term=query,
                                        retstart=retstart,
                                        retmax=retmax, rettype='full',
                                        retmode='text', field='BioSample'))

  def _esearch_data_getter(self, ids):
    '''Get assembly data from esearch ids'''
    #validate=False Fix for a bug which is in the entrez package
    #while this code was written.
    ds = self.ez.read(self.ez.esummary(db="assembly", id=ids,
                                         report="full"),validate=False)
    self.logger.info('parse data')
    return self._parse_document_summary_set(ds)

  def _parse_document_summary_set(self, ds):
    '''Parsing the document summary set metadata from ncbi'''
    data_list = ds['DocumentSummarySet']['DocumentSummary']
    return [self._parse_assembly_data(data) for data in data_list]

  def _parse_assembly_data(self, data):
    '''Parsing the metadata from ncbi'''
    meta = data.pop('Meta', None)
    gb_bioproject = data.pop('GB_BioProjects', None)
    rs_bioproject = data.pop('RS_BioProjects', None)
    sample = data.pop('BioSampleAccn', "")
    sample_source = data.pop('Biosource',None)
    for i in ['GB_Projects','RS_Projects','PropertyList','Synonym']:
        data.pop(i, None) #ignore this info

    if meta:
        meta_tree = ET.fromstring('<root>'+meta+'</root>')

    if gb_bioproject:
        gb_acc = gb_bioproject[0]['BioprojectAccn']

    if rs_bioproject:
        rs_acc = rs_bioproject[0]['BioprojectAccn']
        data['RS_BioProjectAccn'] = rs_acc

    strain = ""
    if sample_source:
        l = sample_source['InfraspeciesList']
        for dic in l:
            if dic['Sub_type'] == 'strain':
                strain = dic['Sub_value']

    s = []
    for stat in meta_tree.findall('Stats/Stat'):
        s.append(merge_dict(stat.attrib, {'value':stat.text}))
    return {'project':gb_acc, 'sample':sample,
            'strain':strain, 'stats':s, 'attributes':data}

  def _post_process_assembly_data(self, d, i):
        '''put assembly data in db'''
        matches = self.db.get_data("match (stu:study)--(sam:sample)-"
                                   "-(satt:sample_attrib) "
                                   "where sam.EXTERNAL_ID='%s' "
                                   "return stu, sam, satt" % d['sample'])
        projects = [match['stu']['alias'] for match in matches]
        strains = [match['satt']['strain'] for match in matches]
        replace_proj = None
        replace_strain = None
        if all([project != d['project'] for project in projects]):
                replace_proj = d['project']
        if all([strain != d['strain'] for strain in strains]):
                replace_strain = d['strain']
        if any([replace_proj,replace_strain]):
            #let it run unsafe as errors will get catched by AsyncEntrez
            self.db.unsafe_run_cql(self._cql_replace(d['sample'],
                            replace_proj, replace_strain))
        #let it run unsafe as errors will get catched by AsyncEntrez
        self.db.unsafe_run_cql(self._cql_assembly_data(d['project'], d['sample'],
                                                 d['stats'], d['attributes']))

  def _cql_assembly(self, stats, attributes):
    '''Create a cypher for assembly and its stats'''
    cql = []
    cql.append(cql_create("assembly", escape_attrib(attributes), 'ably'))
    for z, stat in enumerate(stats):
        cql.append(cql_create("assembly_stats", escape_attrib(stat),
                              'sta%s' % z))
        cql.append(cql_relation('ably','hasStats','sta%s' % z))
    return ' '.join(cql)

  def _cql_assembly_data(self, project, sample, stats, attributes):
    '''Create a cypher for assembly, stats and its relationships'''
    cql = [("match (stu:study)--(sam:sample)--(satt:sample_attrib) "
            "where sam.EXTERNAL_ID='{sam}' "
            "and stu.alias='{pro}'").format(sam=sample, pro=project)]
    cql.append(self._cql_assembly(stats, attributes))
    cql.append(cql_relation('stu','hasAssembly','ably'))
    cql.append(cql_relation('sam','hasAssembly','ably'))
    return ' '.join(cql)

  def _cql_replace(self, sample, replace_proj=None, replace_strain=None):
    """Create cypher to replace strain and project attributes if
    they are different in ncbi's assembly and sra database"""
    cql = [("match (stu:study)--(sam:sample)--(satt:sample_attrib) "
            "where sam.EXTERNAL_ID='%s'" % sample)]
    if replace_proj:
        cql.append("set stu.sra_alias = stu.alias")
        cql.append("set stu.alias = '%s'" % replace_proj)
    if replace_strain:
        cql.append("set satt.sra_strian = satt.strain")
        cql.append("set satt.strain = '%s'" % replace_strain)
    cql.append('return stu') #set return statement if neiter is set
    return ' '.join(cql)

  def _esearch_initial(self, query):
    '''initial esearch of assembly - needed for count'''
    return self.ez.read(self.ez.esearch(db='assembly', term=query,
                                        field='BioSample'))

  def _async_esearch(self, query, retmax=500, batch = 100):
    '''Create async class and start it for assembly'''
    self.asy = AsyncEntrez(self, fun_initial=self._esearch_initial,
                      fun_id_producer=self._esearch_assembly_ids,
                      fun_data_parser=self._esearch_data_getter,
                      fun_db_consumer=self._post_process_assembly_data,
                      retmax = retmax, batch = batch)
    self.asy.db_signal.connect(self._handle_db_signal)
    self.asy.parser_signal.connect(self._handle_parser_signal)
    self.asy.producer_signal.connect(self._handle_producer_signal)
    self.asy.async_from_query(query)


class DB_Runner(QRunnable):
    '''
    Runner class for QThread to fill database

    Args:
        parent: needed for abort event and logger name
        fun: function to call by the runner

    Attributes:
        fun: holds the fun to fill the db
    '''

    def __init__(self, parent, fun):
        super(DB_Runner, self).__init__()
        self.parent = parent
        self.logger_name = '{}.DB_Runner'.format(self.parent.logger_name)
        self.logger = logging.getLogger(self.logger_name)
        self.fun = fun

    def run(self):
        '''Start runner'''
        while not (self.parent.db_queue.empty() and
                   self.parent.pars.is_set()):
            if self.parent.event_abort.is_set():
                break
            try:
                self.logger.info('db_size: %s' % self.parent.db_queue.qsize())
                d = self.parent.db_queue.get(False)
            except queue.Empty:
                time.sleep(0.5)
            else:
                try:
                    self.fun(d, self.parent.db_counter)
                    self.parent._db_checker()
                except Exception as exc:
                    self.parent.handle_error('DB_Runner', exc)
        self.logger.info("Consumer queue empty finished. Exiting")

class ID_Runner(QRunnable):
    '''
    Runner class for QThread to get ids

    Args:
        parent: needed for abort event and logger name
        fun: function to call by the runner
        retstart: start id for esearch
        retmax: max # of return values from esearch

    Attributes:
        fun: holds the fun to get the ids
        retstart: holds the restart arg
        retmax: holds the retmax arg
    '''

    def __init__(self, parent, fun, retstart, retmax):
        super(ID_Runner, self).__init__()
        self.parent = parent
        self.logger_name = '{}.ID_Runner'.format(self.parent.logger_name)
        self.logger = logging.getLogger(self.logger_name)
        self.retstart = retstart
        self.retmax = retmax
        self.fun = fun

    def run(self):
        '''start runner'''
        self.logger.info("Id producer started "
                         "with retstart: {}".format(self.retstart))
        if not self.parent.event_abort.is_set():
            try:
                data = self.fun(self.retstart, self.retmax)
                ids = data['IdList']
                #self.logger.info('ID producer got {}'.format(ids))
                [self.parent.id_queue.put(_id) for _id in ids]
                #no signals possible in qrunnable itself
                #manage it in parent instead
                self.parent._producers_checker()
            except Exception as exc:
                self.parent.handle_error('ID_Runner', exc)
        self.logger.info("Id producer finished, exiting")

class Parser_Runner(QRunnable):
    '''
    Runner class for QThread to parse id to data for db

    Args:
        parent: needed for abort event and logger name
        fun: function to call by the runner
        batch: size of ids to get from esearch in one go
        i: Int of this parser - for logging only

    Attributes:
        fun: holds the fun to get data from id
        batch: holds the batch arg
        i: holds the i arg
    '''

    def __init__(self, parent, fun, batch, i):
        super(Parser_Runner, self).__init__()
        self.parent = parent
        self.logger_name = '{}.Parser_Runner'.format(self.parent.logger_name)
        self.logger = logging.getLogger(self.logger_name)
        self.fun = fun
        self.batch = batch
        self.i = i

    def __get_data_from_ids_helper(self, ids):
        ids = ', '.join(ids)
        ts = time.time()
        data = self.fun(ids)
        td = time.time()-ts
        #process should at least take 1 sec (be nice to ncbi)
        if (1-td) > 0:
            time.sleep(1-td)
        return data   

    def run(self):
        '''start runner'''
        self.logger.info("ID Parser Nr. {} started".format(self.i))
        while not (self.parent.id_queue.empty() and 
                   self.parent.prod.is_set()):
            if self.parent.event_abort.is_set():
                break
            self.logger.info('id_size: %s' % self.parent.id_queue.qsize())
            id_list = []
            for _ in range(self.batch):
                try:
                    id_list.append(self.parent.id_queue.get(False))
                except queue.Empty:
                    pass
            if id_list:
                self.logger.info('getting data of ids: {}'.format(id_list))
                try:
                    data = self.__get_data_from_ids_helper(id_list)
                    self.logger.info('putting data to db queue')
                    [self.parent.db_queue.put(d) for d in data]
                except Exception as exc:
                    self.parent.handle_error('Parser_Runner', exc)
            else:
                time.sleep(0.5)
        self.parent._parser_checker()
        self.logger.info("Id consumer, db producer "
                         "Nr. %s finished, exiting" % self.i)

class AsyncEntrez(QObject):
    '''
    QObject to async get data and load into db from entrez in three steps:
    - Get ids from esearch query
    - Get data from id on esearch
    - Put data into db

    Args:
        parent: parten class that calls this class
        fun_initail: Fun with initial esearch result - needed for max count
        fun_id_producer: Function which produces the ids
        fun_data_parser: Function which gets the data from ids
        fun_db_consumer: Function which puts the parsed data into the db
        retmax: Max # of simultain returns form esearch
        batch: Max # to handle while parsing
        max_parsers: # of parsers to use
        start_id: start with this id for the db consumer

    Attributes:
        matches the args

    Signals:
        producer_signal(int, int): Producer int of int finished
        parser_signal(int, int): Parser int of int finished
        db_signal(int, int): Databes entry int of int finished
    '''

    producer_signal = pyqtSignal(int, int)
    parser_signal = pyqtSignal(int, int)
    db_signal = pyqtSignal(int, int)

    def __init__(self, parent, fun_initial, fun_id_producer, fun_data_parser,
                 fun_db_consumer, retmax=500, batch=100, max_parsers=2,
                 start_id=0):
        super(AsyncEntrez, self).__init__()
        self.parent = parent
        self.logger_name = '{}.AsyncEntrez'.format(parent.logger_name)
        self.logger = logging.getLogger(self.logger_name)
        self.fun_initial = fun_initial
        self.fun_id_producer = fun_id_producer
        self.fun_data_parser = fun_data_parser
        self.fun_db_consumer = fun_db_consumer
        self.retmax = 500 if retmax <= 0 else retmax
        if max_parsers > 3:
            self.logger.warning("Max parser > 3 (is: {}). NCBI may prevent "
                                "more than 3 requests per second. "
                                "Data could be corrupted".format(max_parsers))
        self.max_parsers = 2 if max_parsers <=0 else max_parsers
        self.batch = 100 if batch <= 0 else batch
        self.id_queue = queue.Queue()
        self.db_queue = queue.Queue()
        self.prod = threading.Event()
        self.pars = threading.Event()
        self.event_abort = threading.Event()
        self.error = False
        self.abort = False
        self.db_counter = start_id  

    def handle_error(self, s, e):
        '''Make sure exceptions are not swallowed by ThreadedPoolExtractor'''
        self.prod.set()
        self.pars.set()
        self.error = True
        self.event_abort.set()
        self.logger.error('%s generated an exception: %s' % (s, e))

    def _abort(self):
        self.logger.warning('Abort async entrez')
        self.abort = True
        self.prod.set()
        self.pars.set()
        self.event_abort.set()

    def _db_checker(self):
        '''increas the db_counter for db consumer and emit the db signal'''
        #is save as there is only one worker on this counter
        self.db_counter += 1
        self.db_signal.emit(self.db_counter, self.count)

    def _producers_checker(self):
        '''Called when a producer finished and set event if all concluded'''
        self.producers_counter += 1
        self.producer_signal.emit(self.producers_counter, self.max_producers)
        if self.producers_counter == self.max_producers:
            self.logger.info('about to set prod event')
            self.prod.set()

    def _parser_checker(self):
        '''Called when a parser finished and set event if all concluded'''
        self.parsers_counter += 1
        self.parser_signal.emit(self.parsers_counter, self.max_parsers)
        if self.parsers_counter == self.max_parsers:
            self.logger.info('about to set parser event')
            self.pars.set()

    def async_from_query(self, query):
        '''Get the data from query and put them into the db - Async'''
        data = self.fun_initial(query)
        self.logger.info('got initial data from web')
        self.count = int(data['Count'])
        self.logger.info('count: %s' % self.count)
        self.max_producers = len(list(range(0, self.count, self.retmax)))
        self.producers_counter = 0
        self.parsers_counter = 0
        if self.count == 0:
            self.logger.warning("Query '{}' results in no data to "
                                "fetch from ncbi. "
                                "Exiting function.".format(query))
            return None
        self.pool = QThreadPool.globalInstance()
        #worker 1 empty queue for database
        db_worker = DB_Runner(self, self.fun_db_consumer)
        self.pool.start(db_worker)
        #worker 2 for parser
        parser_worker = Parser_Runner(self, self.fun_data_parser, self.batch, 0)
        self.pool.start(parser_worker)
        #sleep some time between starts so we are nice to ncbi
        for retstart in range(0, self.count, self.retmax):
            id_fun = dbl = partial(self.fun_id_producer, query)
            id_worker = ID_Runner(self, id_fun, retstart, self.retmax)
            self.pool.start(id_worker)
            time.sleep(1)
        for i in range(1, self.max_parsers):
            #start more workers now
            parser_worker = Parser_Runner(self, self.fun_data_parser, self.batch, i)
            self.pool.start(parser_worker)
        self.pool.waitForDone()

