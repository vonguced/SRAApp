"""DB handlers for DB and statistics in Neo4j

This module contains all the classes needed to connect to neo4j and run cyphers.
"""

from collections import Counter
from neo4j import GraphDatabase
from database.xml_keywords import *
from database.helper_functions import *
import subprocess
import logging

class DBStatistics():
  '''
  Class with handy statistic data from a SRAMetadataDB
  Contains all the function for selector buttons

  Args:
      db (SRAMetadataDB): Database to get statistics from

  Attributes:
      db: Neo4j Database provieded by args
  '''
  def __init__(self, db):
    super(DBStatistics, self).__init__()
    self.db = db
    self.logger_name = '{}.DBStatistics'.format(self.db.logger_name)
    self.logger = logging.getLogger(self.logger_name)

  def number_of(self,node_label):
    '''Count nodes with specified node label'''
    return len(self.db.get_data("match (n:%s) return n" % node_label))

  def _count_dict(self, cql, name):
    '''Count the occurences of name in properties of specified cypher'''
    records = self.db.get_data(cql)
    d = dict(Counter([record[name] for record in records]))
    if None in d.keys():
      d.pop(None)
    return d

  def _count_dict_helper(self, attrib, prop):
    '''Helper function for correct count of runs with matching cqls'''
    if attrib in ["sample_attrib", "library"]:
      cql = (f"MATCH (n:{attrib})--()--(:experiment)--(r:run) "
             f"return n.{prop} as {prop}")
    elif attrib in ["sample", "platform"]:
      cql = (f"MATCH (n:{attrib})--(:experiment)--(r:run) "
             f"return n.{prop} as {prop}")
    elif attrib == "assembly":
      cql = (f"MATCH (n:{attrib})--(:sample)--(:experiment)--(r:run) "
             f"return n.{prop} as {prop}")
    elif attrib == "sra_file":
      cql = f"match (n:{attrib})--(r:run) return n.{prop} as {prop}"
    else:
      self.logger.warning(f"Count dict with unknown attrib: {attrib} "
                          "- Fix if you need correct counts")
      cql = f"match (n:{attrib}) return n.{prop} as {prop}"
    return self._count_dict(cql, prop)

  def _exp_pkg_helper(self, match, var_prop, var_ret, prop, vals, exclusive):
    '''Helper function for experiment packages'''
    excl = self._exp_pkg_exclusive(var_prop, prop, exclusive)
    v = list2str(vals)
    cql = (f"match {match} "
           f"where {var_prop}.{prop} in {v} "
           f"{excl}"
           f"RETURN {var_ret}.exp_pkg")
    return self.get_data_value(cql)

  def _exp_pkg_satt_helper(self, prop, vals, exclusive):
    '''Helper for experiment packages of sample_attrib'''
    return self._exp_pkg_helper(
      "(e:experiment)--(s:sample)--(satt:sample_attrib)",
      "satt", "e", prop, vals, exclusive)

  def _exp_pkg_assembly_helper(self, prop, vals, exclusive):
    '''Helper for experiment packages of assembly'''
    return self._exp_pkg_helper(
      "(e:experiment)--(s:sample)--(a:assembly)",
      "a", "e", prop, vals, exclusive)

  def _bases_helper(self, subkey):
    '''Helper for different keys in bases'''
    d = self.bases_of_runs()
    new = dict()
    for k, v in d.items():
      if subkey in v:
        new[k] = v[subkey]
    return new

  def _exp_pkg_bases_helper(self, prop, min_val, max_val, exclusive):
    '''Helper for experiment packages of bases histograms'''
    exl = self._exp_pkg_exclusive('b', prop, exclusive)
    cql = ("match (b:bases)--(r:run) "
           f"where {min_val} < b.{prop} "
           f"and b.{prop} < {max_val} "
           f"{exl}"
           "return r.exp_pkg")
    return self.get_data_value(cql)

  def _exp_pkg_assembly_stats_helper(self, prop, min_val, max_val, exclusive):
    '''Helper for experiment packages of assembly histograms'''
    exl = ""
    if not exclusive:
      exl = ("union match (e:experiment) "
             "where not (e)--(:sample)--(:assembly) "
             "return e.exp_pkg as exp")
    cql = ("match (a:assembly_stats)--()--(:sample)--(e:experiment) "
           f"where a.category = '{prop}' "
           f"and {min_val} < a.value "
           f"and a.value < {max_val} "
           "return e.exp_pkg as exp "
           f"{exl}")
    return self.get_data_value(cql)

  def __assembly_stats(self, cat):
    '''Helper for assembly histograms'''
    data = self.db.get_data("match (a:assembly)--(n:assembly_stats) "
                            "where n.category='{}' "
                            "return a.AssemblyName as name, "
                            "n.value as val ".format(cat))
    d = dict()
    for rec in data:
      d[rec["name"]] = rec['val']
    return d

  def _exp_pkg_sample_helper(self, prop, vals, exclusive):
    '''Helper for experiment package of sample'''
    return self._exp_pkg_helper("(e:experiment)--(s:sample)",
                                "s", "e", prop, vals, exclusive)

  def _exp_pkg_platform_helper(self, prop, vals, exclusive):
    '''Helper for experiment package of platform'''
    return self._exp_pkg_helper("(e:experiment)--(p:platform)",
                                "p", "e", prop, vals, exclusive)

  def get_data_value(self, cql):
    '''Get record values from cql directly'''
    return [i.value() for i in self.db.get_data(cql)]

  def _exp_pkg_exclusive(self, var, prop, exclusive):
    '''cql string for exclusive match'''
    if not exclusive:
      return "or not exists({var}.{prop}) ".format(var=var,
                                                   prop=prop)
    return ""

  def taxon_ids(self):
    '''Sum counter for taxon ids'''
    return dict2tuplelist(self._count_dict_helper("sample", xml_TAXON_ID))

  def exp_pkg_tax_ids(self, tax_ids, exclusive):
    '''Experiment packages from taxon ids'''
    return self._exp_pkg_sample_helper(xml_TAXON_ID, tax_ids, exclusive)

  def scientific_names(self):
    '''Sum counter for scientific names'''
    return dict2tuplelist(self._count_dict_helper("sample",
                                                  xml_SCIENTIFIC_NAME))

  def exp_pkg_sci_names(self, sci_names, exclusive):
    '''Experiment packages from scientific names'''
    return self._exp_pkg_sample_helper(xml_SCIENTIFIC_NAME, sci_names,
                                       exclusive)

  def strains(self):
    '''Sum counter for strains'''
    return dict2tuplelist(self._count_dict_helper("sample_attrib", "strain"))

  def exp_pkg_strains(self, strains, exclusive):
    '''Experiment packages from strains'''
    return self._exp_pkg_satt_helper("strain", strains, exclusive)

  def isolation_source(self):
    '''Sum counter for isolation_source'''
    return dict2tuplelist(self._count_dict_helper("sample_attrib",
                                                  "isolation_source"))

  def exp_pkg_isolation_source(self, isolation_sources, exclusive):
    '''Experiment packages from isolation source'''
    return self._exp_pkg_satt_helper("isolation_source", isolation_sources,
                                      exclusive)

  def isolate(self):
    '''Sum counter for isolates'''
    return dict2tuplelist(self._count_dict_helper("sample_attrib", "isolate"))

  def exp_pkg_isolate(self, isolates, exclusive):
    '''Experiment packages from isolates'''
    return self._exp_pkg_satt_helper("isolate", isolates, exclusive)

  def isolate_name_alias(self):
    '''Sum counter for isolate names'''
    return dict2tuplelist(self._count_dict_helper("sample_attrib",
                                                  "isolate_name_alias"))

  def exp_pkg_isolate_name_alias(self, isolate_name_aliases, exclusive):
    '''Experiment packages from isolate names'''
    return self._exp_pkg_satt_helper("isolate_name_alias",
                                      isolate_name_aliases, exclusive)

  def collection_date(self):
    '''Sum counter for collection_dates'''
    return dict2tuplelist(self._count_dict_helper("sample_attrib",
                                                  "collection_date"))

  def exp_pkg_collection_date(self, collection_dates, exclusive):
    '''Experiment packages from collection dates'''
    return self._exp_pkg_satt_helper("collection_date",
                                      collection_dates, exclusive)

  def geo_loc_name(self):
    '''Sum counter for geo locations'''
    geo_data = dict2tuplelist(self._count_dict_helper("sample_attrib",
                                                      "geo_loc_name"))
     #with post process there is always a :
    return [tuple(k.split(":") + [v]) for k, v in geo_data]

  def exp_pkg_geo_loc_name(self, geo_loc_names, exclusive):
    '''Experiment packages from location names'''
    geo_loc_names = [c+':'+l for c,l in geo_loc_names]
    return self._exp_pkg_satt_helper("geo_loc_name",
                                      geo_loc_names, exclusive)

  def env_material(self):
    '''Sum counter for environment'''
    return dict2tuplelist(self._count_dict_helper("sample_attrib",
                                                  "env_material"))

  def exp_pkg_env_material(self, env_materials, exclusive):
    '''Experiment packages from environment'''
    return self._exp_pkg_satt_helper("env_material",
                                      env_materials, exclusive)

  def host(self):
    '''Sum counter for host'''
    return dict2tuplelist(self._count_dict_helper("sample_attrib", "host"))

  def exp_pkg_host(self, hosts, exclusive):
    '''Experiment packages from hosts'''
    return self._exp_pkg_satt_helper("host",
                                      hosts, exclusive)

  def sample_type(self):
    '''Sum counter for sample_type'''
    return dict2tuplelist(self._count_dict_helper("sample_attrib",
                                                  "sample_type"))

  def exp_pkg_sample_type(self, sample_types, exclusive):
    '''Experiment packages from sample type'''
    return self._exp_pkg_satt_helper("sample_type",
                                      sample_types, exclusive)

  def platform_types(self):
    '''Sum counter for platform types'''
    return dict2tuplelist(self._count_dict_helper("platform", "type"))

  def exp_pkg_plt_types(self, p_types, exclusive):
    '''Experiment packages from platform type'''
    return self._exp_pkg_platform_helper("type", p_types, exclusive)

  def platform_models(self):
    '''Sum counter for platform models'''
    pmod = self.db.get_data("MATCH (n:platform) "
                            "return n.model as plat_model")
    return [r['plat_model'] for r in pmod]

  def exp_pkg_plt_models(self, p_models, exclusive):
    '''Experiment packages from platform models'''
    return self._exp_pkg_platform_helper("model", p_models, exclusive)

  def library_strategies(self):
    '''Sum counter for library strategies'''
    return dict2tuplelist(self._count_dict_helper("library",
                                                  xml_LIBRARY_STRATEGY))

  def exp_pkg_lib_strats(self, l_strats, exclusive):
    '''Experiment packages from library strategies'''
    return self._exp_pkg_helper("(s:library)", "s", "s",
                                xml_LIBRARY_STRATEGY, l_strats, exclusive)

  def library_layouts(self):
    '''Sum counter for labrary layouts'''
    return dict2tuplelist(self._count_dict_helper("library",
                                                  xml_LIBRARY_LAYOUT))

  def exp_pkg_lib_layouts(self, l_layouts, exclusive):
    '''Experiment packages from library layouts'''
    return self._exp_pkg_helper("(s:library)", "s", "s",
                                xml_LIBRARY_LAYOUT, l_layouts, exclusive)

  def assembly_submission_date(self):
    '''Sum counter for assembly submission date'''
    return dict2tuplelist(self._count_dict_helper("assembly",
                                                  "SubmissionDate"))

  def exp_pkg_assembly_submission_date(self, submission_dates, exclusive):
    '''Experiment packages from submission date'''
    return self._exp_pkg_assembly_helper("SubmissionDate",
                                         submission_dates, exclusive)

  def sra_date(self):
    '''Sum counter for sra date'''
    return dict2tuplelist(self._count_dict_helper("sra_file", "date"))

  def exp_pkg_sra_date(self, dates, exclusive):
    '''Experiment packages from sra dates'''
    return self._exp_pkg_helper("(r:run)--(sra:sra_file)", "sra", "r",
                                "date", dates, exclusive)

  def organizations(self):
    '''Sum counter for organizations'''
    orgs = self.db.get_data(
      "MATCH (n:organization) return n.{} as org".format(xml_Name))
    return [r['org'] for r in orgs]

  def exp_pkg_org_names(self, org_names, exclusive):
    '''Experiment packages from organisations'''
    return self._exp_pkg_helper(
      "(o:organization)--()--(e:experiment)",
      "o", "e", xml_Name, org_names, exclusive)

  def bases_of_runs(self):
    '''Bases per run'''
    data = self.db.get_data("MATCH (run:run)-[:hasBases]->(bases)"
                            "return bases, run")
    d = dict()
    for rec in data:
      d[rec["run"]["accession"]] = dict(rec['bases'])
    return d

  def exp_pkg_min_bases(self, min_bases):
    '''Experiment packages from minimal bases'''
    cql = ("match (r:run) "
           "where r.total_bases > {bases:.0f} "
           "return r.exp_pkg")
    return self.get_data_value(cql.format(bases=min_bases))

  def count_bases(self):
    '''Total count of bases'''
    return self._bases_helper('count')

  def exp_pkg_count_bases(self, min_val, max_val, exclusive):
    '''Experiment packages from count bases histogram'''
    return self._exp_pkg_bases_helper('count', min_val, max_val, exclusive)

  def n_bases(self):
    '''All n bases in db'''
    return self._bases_helper('N')

  def exp_pkg_n_bases(self, min_val, max_val, exclusive):
    '''Experiment packages from n bases histogram'''
    return self._exp_pkg_bases_helper('N', min_val, max_val, exclusive)

  def gc_ratios(self):
    '''All gc-ratios in db'''
    return self._bases_helper('GC_Ratio')

  def exp_pkg_gc_ratios(self, min_val, max_val, exclusive):
    '''Experiment packages from gc ratios histogram'''
    return self._exp_pkg_bases_helper('GC_Ratio', min_val, max_val, exclusive)

  def exp_pkg_assembly(self):
    '''Experiment packages from assembly'''
    cql = ("match (e:experiment)--(s:sample)--(a:assembly) "
           "return e.exp_pkg")
    return self.get_data_value(cql)

  def assembly_l50(self):
    '''All l50 values in db'''
    return self.__assembly_stats('contig_l50')

  def exp_pkg_assembly_l50(self, min_val, max_val, exclusive):
    '''Experiment packages from assembly l50'''
    return self._exp_pkg_assembly_stats_helper('contig_l50',
                                               min_val, max_val,
                                               exclusive)

  def assembly_n50(self):
    '''All n50 values in db'''
    return self.__assembly_stats('contig_n50')

  def exp_pkg_assembly_n50(self, min_val, max_val, exclusive):
    '''Experiment packages from assembly n50'''
    return self._exp_pkg_assembly_stats_helper('contig_n50',
                                               min_val, max_val,
                                               exclusive)

  def assembly_contig_count(self):
    '''All contig values in db'''
    return self.__assembly_stats('contig_count')

  def exp_pkg_assembly_contig_count(self, min_val, max_val, exclusive):
    '''Experiment packages from assembly contig count'''
    return self._exp_pkg_assembly_stats_helper('contig_count',
                                               min_val, max_val,
                                               exclusive)


class SRAMetadataDB():
  '''
        Class connection helper for Neo4j communication

        Args:
            uri (str): network location of neo4j database
            user (str): user name for neo4j database
            password (str): password for neo4j database

        Optional Args:
            database (str): name of database (default: 'raw')

        Attributes:
            driver: Neo4j DB Driver
            database_name: Name of database from optional arg
    '''
  def __init__(self, parent, uri, user, password, database='raw'):
      super(SRAMetadataDB, self).__init__()
      self.parent = parent
      self.database_name = database
      if not parent:
        self.logger_name = 'SRAMetadataDB_{}'.format(self.database_name)
      else:
        pl, dn = self.parent.logger_name, self.database_name
        self.logger_name = f'{pl}.SRAMetadataDB_{dn}'
      self.logger = logging.getLogger(self.logger_name)
      self.driver = GraphDatabase.driver(uri, auth=(user, password))

  def __del__(self):
      if hasattr(self, 'driver'):
          self.driver.close()

  def close(self):
      '''Close the connection to the neo4j database'''
      self.__del__()

  def count_relationships(self):
      '''Count all relationships in neo4j database'''
      cql = "match (n)-[r]->(m) return count(r) as relationships"
      return self.get_data(cql)[0]['relationships']

  def count_nodes(self):
      '''Count all nodes in neo4j database'''
      cql = "match (n) return count(n) as nodes"
      return self.get_data(cql)[0]['nodes']

  def run_cql(self, cql):
    '''Run the provieded cypher - capture error in log on fail'''
    try:
      self.unsafe_run_cql(cql)
    except Exception as exc:
      self.logger.error("run_cql not working\n"
                        "Cql: {cql} generated an exception:\n"
                        "{exc}".format(cql=cql, exc=exc))
    return None

  def unsafe_run_cql(self, cql):
    '''Run the provided cypher - no error captured'''
    with self.driver.session(database=self.database_name) as session:
      with session.begin_transaction() as tx:
        result = tx.run(cql)
        tx.commit()
        tx.close()

  def batch_run_cql(self, cql, batch):
    '''Run the provided cypher with the provided batch data'''
    with self.driver.session(database=self.database_name) as session:
      with session.begin_transaction() as tx:
        tx.run(cql, batch=batch)
        tx.commit()
        tx.close()

  def get_data(self, cql):
    '''Get the data from provieded cypher - capture error in log on fail'''
    result = self.driver.session(database=self.database_name).run(cql)
    return [rec for rec in result]

  def clear_db(self):
    '''Clear the whole database - capture error in log on fail'''
    try:
      with self.driver.session(database=self.database_name) as session:
          session.run("MATCH (n) DETACH DELETE n")
          session.run("CALL apoc.schema.assert({}, {})")
    except Exception:
      self.logger.error("clear_db not working -"
                        " Connection to DB may be down")
    return None

  def export_all(self, filename):
    '''Export database to file: filename'''
    try:
      with self.driver.session(database=self.database_name) as session:
          session.run(
              "CALL apoc.export.cypher.all('%s',{format:'cypher-shell'})"
              % filename)
    except Exception:
      self.logger.error("export_all not working -"
                        " Connection to DB may be down")
    return None

  def import_from_cypher_file(self, neo4j_home, filename, user, password):
    '''Import database from file: filename
    neo4j_home referse to the path of the bin directory 
    where cypher-shell is located
    user and password must be provided for neo4j'''
    try:
      subprocess.run("cat %simport/%s " % (neo4j_home, filename) +
                     " | %sbin/cypher-shell -u %s -p %s --database %s" %
                     (neo4j_home, user, password, self.database_name)
                    , shell=True)
    except Exception:
      self.logger.error("import_from_cypher_file not working - "
                        "Connection to DB may be down or "
                        "wrong Neo4jHome is set"
                        "Neo4jHome: {}".format(neo4j_home))
    return None



