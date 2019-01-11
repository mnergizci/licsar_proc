#!/usr/bin/env python
"""
Make interferograms

========
Overview
========
This script is part of the main LiCSAR processing chain. It requires LiCSAR_02_coreg.py to have been completed successfully for all slaves. This script calculates the topographic phase and calculates the differential interferogram between the image and the three images that were acquired before it.

=========
Changelog
=========
November 2016: Original implementation (Karsten Spaans, Uni of Leeds)


=====
Usage
=====
LiCSAR_03_mk_ifgs.py -f <framename> -d </path/to/processing/location>

    -f    Name of the frame to be processed in database
    -d    Path to the processing location. 
    -j    job id
    -i    ifg list file
    -p    polygon
    -z    sip file
    -y    batch mode
    -c <level> clean rslcs after succesful interferogram creation, acording to level:
            0 - keep rslcs and subswathes (default)
            1 - keep only subswathes. Subswathes may be required during 
                coregistration and rslcs will be rebuild by mk_ifgs if required, 
                this is a fairly safe option which reduces space.
            2 - clean rslc's and subswathes after interferogram creation.
    -T <file> Write to report file <file>. Defaults to FRAME-mk-ifgs-report
"""

################################################################################
#Imports
################################################################################
import getopt
import os
import sys
import datetime as dt
import re

from LiCSAR_lib.LiCSAR_misc import *
from LiCSAR_lib.ifg_lib import *
from LiCSAR_lib.coreg_lib import rebuild_rslc
# from LiCSAR_02_coreg import grep
#Import gamma wrapper and global config
from gamma_functions import *
import global_config as gc
import pdb

################################################################################
#Main function
################################################################################
def main(argv=None):
############################################################ Init. params
    if argv == None:
        argv = sys.argv

    procdir = []
    framename = []
    job_id = -1
    ifgListFile = None
    cleanLvl = 0
    reportfile = None
############################################################ Process Args.
    try:
        try:
            opts, args = getopt.getopt(argv[1:], "vhi:f:d:j:y:p:z:c:T:", ["version", "help"])
        except getopt.error, msg:
            raise Usage(msg)
        for o, a in opts:
            if o == '-h' or o == '--help':
                print __doc__
                return 0
            elif o == '-v' or o == '--version':
                print ""
                print "Current version: %s" % gc.config['VERSION']
                print ""
                return 0
            elif o == '-f':
                framename = a
            elif o == '-d':
                procdir = a
            elif o == '-i':
                ifgListFile = a
            elif o == '-j':
                job_id = int(a)
            elif o == '-y':
                gc.batchflag = int(a)
            elif o == '-z':
                ziplistfile = a
            elif o == '-p':
                polygonfile = a
            elif o == '-c':
                cleanLvl = int(a)
            elif o == '-T':
                reportfile = a


        if not framename:
            raise Usage('No frame name given, -f option is not optional!')
        if not procdir:
            raise Usage('No output data directory given, -d is not optional!')
        if job_id == -1:
            print "This processing is not outputting any products to the database."
        if gc.batchflag:
            if not(polygonfile) or not(ziplistfile):
                raise Usage("Polygon file AND ziplist file are required in batch mode.")
            import LiCSquery_batch
            global lq
            lq = LiCSquery_batch.dbquery(ziplistfile, polygonfile)
        else:
            import LiCSquery as lq

    except Usage, err:
        print >>sys.stderr, "\nERROR:"
        print >>sys.stderr, "  "+str(err.msg)
        print >>sys.stderr, "\nFor help, use -h or --help.\n"
        return 2

############################################################ Ensure connected to database
    if not lq.connection_established():
        print >> sys.stderr, "\nERROR:"
        print >> sys.stderr, "Could not establish a stable database connection. No processing can happen."
        return 1

############################################################ Make sure critical data is available in database
    if not lq.check_frame(framename):
        print >>sys.stderr, "\nERROR:"
        print >>sys.stderr, "Frame {0} was not found in database.".format(framename)
        return 1

    if not os.path.exists(procdir):
        print >>sys.stderr, "\nERROR:"
        print >>sys.stderr, "Processing directory {0} does not seem to exist.".format(procdir)
        return 1

############################################################ Ensure previous processing products are available
    rslcdir = os.path.join(procdir,'RSLC')
    if not os.path.exists(rslcdir):
        print >>sys.stderr, "\nERROR:"
        print >>sys.stderr, "Can't find RSLC directory in processing directory {0}.".format(procdir)
        return 1

############################################################ Find the master date associated with the height file (prev processing step)
    masterdatestr = []
    geodir = os.path.join(procdir,'geo')
    geodirlist = os.listdir(geodir)
    for l in geodirlist:
        if l[-4:] == '.hgt' and l[0] == '2':
            masterdatestr = l[:8]
    if masterdatestr:
        masterdate = dt.date(int(masterdatestr[:4]),int(masterdatestr[4:6]),int(masterdatestr[6:8]))
    else:
        print >>sys.stderr, "\nERROR:"
        print >>sys.stderr, "Could not find master date in geocoding directory {0}.".format(geodir)
        return 1
    
############################################################ Parse multilook paramters
    masterslcdir = os.path.join(procdir,'SLC',masterdatestr)

    gc.rglks = int(grep('range_looks',os.path.join(masterslcdir,masterdate.strftime('%Y%m%d')+'.slc.mli.par')).split(':')[1].strip())
    gc.azlks = int(grep('azimuth_looks',os.path.join(masterslcdir,masterdate.strftime('%Y%m%d')+'.slc.mli.par')).split(':')[1].strip())

############################################################ Get a list of co registered slaves and dates
    date_pairs = []
    if ifgListFile:
        procslavelist = list()
        with open(ifgListFile) as f:
            for line in f:
                mtch = re.search('(\d+)[-_\s]+(\d+)',line)
                procslavelist += mtch.groups()
                date_pair = [dt.datetime.strptime(ds,'%Y%m%d') for ds in mtch.groups()]
                date_pairs.append(date_pair)

        print date_pairs
        procslavelist = list(set(procslavelist))

    else:
        procslavelist = sorted([s for s in os.listdir(rslcdir) if (os.path.isdir(os.path.join(rslcdir,s)) and len(s) == 8)])
        # procslavelist_dt = [dt.date(int(d[:4]),int(d[4:6]),int(d[6:])) for d in procslavelist if dt.date(int(d[:4]),int(d[4:6]),int(d[6:]))]


        ##### Calc date pairs (3 either side) from rslc dir
        procslavelist_dt = [dt.datetime.strptime(d,'%Y%m%d') for d in procslavelist]
        procslavelist_dt = sorted(procslavelist_dt,reverse=True)
        while len(procslavelist_dt)>1:
            cur_date = procslavelist_dt.pop() # create pairs for cur date and next 3 dates
            for ix in range(max(-3,-1*len(procslavelist_dt)),0):
                date_pairs.append([cur_date,procslavelist_dt[ix]])


############################################################ Create a report file
    if not reportfile:
        reportfile = os.path.join(procdir,'{0}-mk-ifgs.txt'.format(framename))
    starttime = dt.datetime.now()
    with open(reportfile,'w') as f:
        f.write('LiCSAR_03_mk_ifgs processing started {0}.\n'.format(dt.datetime.now().strftime('%Y-%m-%d %H:%M')))
        f.write('\nMaster date: {0}\n'.format(masterdate))
    
############################################################ 
        for date in procslavelist:
            slaveDate = dt.datetime.strptime(date,'%Y%m%d')
            rc = rebuild_rslc(procdir,slaveDate,masterdate,gc.rglks,gc.azlks)
            if rc == 0:
                f.write('Slave rslc {0} was sucessfully rebuilt\n'.format(slaveDate))
            elif rc == 1:
                f.write('Slave rslc {0} could not be rebuilt\n'.format(slaveDate))
            elif rc == 2:
                f.write('Slave rslc {0} does not have valid IW*.rslc files to mosaic\n'.format(slaveDate))
            elif rc == 3:
                f.write('Slave rslc {0} already exists\n'.format(slaveDate))

############################################################ Loop through and create interferograms 
        procDates = []
        for date_pair in date_pairs:
            rc = make_interferogram(masterdate,date_pair[0],date_pair[1],procdir, lq,job_id)
            if rc == 0:
                f.write('\nSuccesfully created interferogram between {0}:{1}.'.format(*date_pair))
                procDates += date_pair
            if rc == 1:
                f.write('\nInterferogram {0}:{1} had a problem during the offset file creation.'.format(*date_pair))
            if rc == 2:
                f.write('\nInterferogram {0}:{1} had a problem during the topographic phase estimation.'.format(*date_pair))
            if rc == 3:
                f.write('\nInterferogram {0}:{1}: had a problem during the interferogram formation.'.format(*date_pair))
            if rc == 4:
                f.write('\nInterferogram {0}:{1}: had a problem during the sunraster preview creation.'.format(*date_pair))
            if rc == 5:
                f.write('\nInterferogram {0}:{1}: had a problem during the coherence estimation.'.format(*date_pair))

############################################################ Cleanup
        procDates = set(procDates)
        if cleanLvl: # if performing a clean
            for date in procDates:
                rslcDir = os.path.join(procdir,'RSLC',date.strftime('%Y%m%d'))
                iwRslcs = glob(rslcDir+'/*.IW[1-3].rslc')
                rslcPath = os.path.join(rslcDir,date.strftime('%Y%m%d.rslc'))
                # Remove rslcs if subswathes present
                if cleanLvl >= 1 and iwRslcs:
                    os.remove(rslcPath)
                    f.write('\nRSLC for date {0} removed'.format(date))
                # Remove subswathes
                if cleanLvl >= 2:
                    for iwRslc in iwRslcs:
                        os.remove(iwRslc)
                        f.write('\nSubswathe {0} removed'.format(iwRslc))



################################################################################
#Call main function
################################################################################
if __name__ == "__main__":
    sys.exit(main())


    #create offset
    #phase_sim_orb
    #slc_diff_intf
    #base_init
    #rasmph_pwr
    #cc_wave
    #rascc
