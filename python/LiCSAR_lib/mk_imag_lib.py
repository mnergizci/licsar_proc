"""
This module contains functions which are required to read Sentinel-1 files in
SAFE format and convert them to LiCSAR frame image (Gamma SLC).
"""
################################################################################
# Import relevent packages
################################################################################
import getopt
import os
import re
import shutil
import sys
import datetime as dt
import numpy as np
import s1data as s1
# import datetime as dt
import subprocess as subp
from glob import glob
from configparser import SafeConfigParser
import copy
#LiCSAR global configuration
import global_config as gc
import logging
from gamma_functions import *
from LiCSAR_lib.LiCSAR_misc import Usage,cd
from LiCSAR_lib.orbit_lib import getValidOrbFile,logger
#from LiCSAR_db.LiCSquery import get_ipf

################################################################################
# Check Bursts function
################################################################################
def check_bursts( framename, startdate, enddate, licsQuery ):
    """
    Checks if there are associated bursts for the given frame and dates. If not
    found, returns an integer greater than 1. If found returns a burst list,
    filelist and dates.
    """
    burstlist = licsQuery.get_bursts_in_frame( framename )
    if not burstlist:
        print('\nI didn\'t find any bursts associated with '\
                           'frame{0}. Exiting'.format(framename), file=sys.stderr)
        return 1
    else:
        print('\nI found {0} bursts associated with frame {1}, hooray!'.format(
                len( burstlist ), framename ))
    filelist = licsQuery.get_frame_files_period( str(framename), str(startdate), str(enddate) )
    if not filelist:
        print('\nI didn\'t find any files associated with '\
                            'frame{0}. Exiting'.format( framename, startdate,
                                    enddate ), file=sys.stderr)
        return 1
    else:
        dates = set([ f[1] for f in filelist ])
        #if len(dates) == 1:
        #    print('\nI only found one acquisition date '\
        #                        'associated with frame {0} between {1} and '\
        #                        '{2}. Exiting'.format( framename, startdate,
        #                                enddate ), file=sys.stderr)
        #    return 1
        #else:
        print('\nThere are {0} acquisition dates associated with frame '\
                  '{1} between {2} and {3}.'.format( len(dates), framename,
                            startdate, enddate ))
    return burstlist, filelist, dates

################################################################################
#Check master burst function
################################################################################
def check_master_bursts( framename, burstlist, masterdate, dates, licsQuery, midnighterror = False):
    """
    Checks if masterdate was acquired, and if all bursts were acquired on master
    date. Returns greater than 0 if bursts can be found.
    """
    if type(dates) == type(None):
        dates = [masterdate]
    if masterdate in dates:
        masterburstlist = licsQuery.get_frame_bursts_on_date( framename,
                masterdate )
        if midnighterror:
            masterburstlist2 = licsQuery.get_frame_bursts_on_date( framename,
                masterdate + dt.timedelta(days=1) )
            masterburstlist = masterburstlist + masterburstlist2
            
        if masterburstlist:
            missingbursts = [ b[0] for b in burstlist 
                    if not b in masterburstlist ]
            if len(missingbursts) < 1:
                print('\nAll bursts for frame {0} seem to have been '\
                      'acquired on the chosen master date {1}.'.format( 
                              framename, masterdate ))
            else:
                print('\nWarning!\nOne or more bursts from '\
                                    'frame{0} have not been acquired on {1}. '\
                                    'Missing bursts:\n{2}'.format( framename, 
                                            masterdate, '\n'.join([
                                                m for m in missingbursts ])), file=sys.stderr)
                print('\nPlease use the -m option to choose '\
                                    'another master from one of these choices:'\
                                    '\n{0}'.format( ', '.join([ 
                                        m.strftime('%Y%m%d') for m in 
                                        sorted( list( dates )) 
                                        if m != masterdate ])), file=sys.stderr)
                return 1                    
        else:
            print('\nERROR:', file=sys.stderr)
            print('Database search returned an empty list when '\
                                'looking for master date {0} in frame {1}. '\
                                'This should not be happening?'.format( 
                                        masterdate, framename ), file=sys.stderr)
            print('Exiting.', file=sys.stderr)
            return 1
    else:
        print('\nERROR:', file=sys.stderr)
        print('Reference epoch not in date list. Please select a '\
                            'more appropriate epoch to be used as reference.', file=sys.stderr)
        print('Exiting.', file=sys.stderr)
        return 1
    print('No bursts missing')
    return 0

################################################################################
#Rename slc function
################################################################################
def rename_slc( slcoldtab, slcnewtab ):
    """
    Rename the SLC based on SLC tabs
    
    In:
        slcoldtab   SLC tab of original file
        slcnewtab   SLC tab of new file
    """
    #Get file names from tab files
    slc1, slc_par1, tops_par1 = parse_slc_tab( slcoldtab )
    slc2, slc_par2, tops_par2 = parse_slc_tab( slcnewtab )
    #rename files
    shutil.move( slc1, slc2 )
    shutil.move( slc_par1, slc_par2 )
    shutil.move( tops_par1, tops_par2 )

################################################################################
#Get orbit directory function
################################################################################
def get_orb_dir( sat ):
    """
    Get path of orbit directory from config file

    Out:
        path to orbit directory
    """
    return os.path.join(os.environ['ORB_DIR'], sat)


def get_orb_dir_old( sat ):
    parser = SafeConfigParser()
    try:
        parser.read( os.environ[ 'LiCSARconfig' ] )
        if sat == 'S1A':
            try:
                orbdir = parser.get( 'paths', 'S1Aorbitpath' )
            except:
                orbdir = []
        elif sat == 'S1B':
            try:
                orbdir = parser.get( 'paths', 'S1Borbitpath' ) 
            except:
                orbdir = []
        else:
            try:
                orbdir = parser.get('paths', 'S1Corbitpath')
            except:
                orbdir = []
    except:
        orbdir = os.environ[ 'ORBs_DIR' ] + '/' + sat
    return orbdir

################################################################################
#Read files function
################################################################################
def read_files( filelist, slcdir, imdate, procdir, licsQuery, job_id, acqMode='iw', test_crosspol = False):
    """
    Makes symbolic links of all files in filelist in given directory, and reads
    into gamma format
    
    In:
        filelist    list of files including path to be processed
        slcdir      path to SLC directory
        imdate      datetime.date object with acquisition date of files
        procdir     path to processing directory
        ...
        test_crosspol  if True, it will extract only VH (or HV) data - for a test now
    Out:
        Boolean True if successful, False if not
    """
############################################################ make dir.
    imdirthis = os.path.join( slcdir, imdate.strftime( '%Y%m%d' ))
    if not os.path.exists( slcdir ):
        os.mkdir( slcdir )
    if not os.path.exists( imdirthis ):
        os.mkdir( imdirthis )
############################################################ link files
    for f in filelist:
        linkthis = os.path.join( imdirthis, f[1] + '.zip' )
        # Database says file exists, but does it?
        if not os.path.exists( f[2] ):
            print('\nWarning, file {0} does not seem to exist? Please fix '\
                  'database. Skipping date {1}.'.format( f[2], imdate ))
            return False
        if not os.path.exists( linkthis ):
            try:
                os.symlink( f[2], linkthis ) # create symbolic link
            except:
                print('Could not create symbolic link of file {0} in '\
                'directory {1}. Skipping date {2}.'.format( f[2], imdirthis, 
                        imdate ))
                return False
############################################################ Unzip the files
    # Finished linking first to assure all files exist, quicker than finding
    # out after unpacking first file that second file does not exist.
    print('Unzipping files...')
    with cd( imdirthis ):
        for f in filelist:
            # unzipcall = [ 'jar', '-xf', f[1] + '.zip' ]
            # unzipcall = [ 'unzip', f[1] + '.zip' ]
            if test_crosspol:
                unzipcall = [ '7za', '-mmt=4', 'x', '-xr!*vv*', '-xr!*hh*', f[1] + '.zip' ]
            else:
                unzipcall = [ '7za', '-mmt=4', 'x', '-xr!*vh*', '-xr!*hv*', f[1] + '.zip' ]
            try:
                rc = subp.check_call( unzipcall )
            except subp.CalledProcessError:
                print('Could not unzip file {0}, skipping date {1}.'.format( 
                        f[1] + '.zip', imdate ))
                return False
    # Again, ensured all files unzip before moving on
############################################################ Convert to Gamma format
    print('Converting files from SAFE to Gamma format...')
    for f in filelist:
        safedir = os.path.join( imdirthis, f[1] + '.SAFE' )
        logdir = os.path.join( procdir, 'log' )
        if not os.path.exists( logdir ):
            os.mkdir( logdir )
        if acqMode == 'iw':
            for sw in [ 'iw1', 'iw2', 'iw3' ]:
                tiff = glob(
                        os.path.join( safedir, 'measurement', 
                            's1*-{0}-slc-*-*.tiff'.format( sw ))
                        )
                annot = glob(
                        os.path.join( safedir, 'annotation', 
                            's1*-{0}-slc-*-*.xml'.format( sw ))
                        )
                calib = glob(
                        os.path.join( safedir, 'annotation', 'calibration',
                            'calibration-s1*-{0}-slc-*-*.xml'.format( sw ))
                        )
                noise = glob(
                        os.path.join( safedir, 'annotation', 'calibration',
                            'noise-s1*-{0}-slc-*-*.xml'.format( sw ))
                        )
                slcthis = os.path.join( imdirthis, 
                        f[1].split( '_' )[5] + '.' + sw.upper() + '.slc' )
                logfile  = os.path.join( logdir, 
                        'par_S1_SLC_{0}.log'.format( 
                            f[1].split( '_' )[5] + sw.upper()
                            )
                        )
                if len(tiff) > 0:
                    if os.path.exists( tiff[0] ):
                        if not par_S1_SLC( tiff[0], annot[0], calib[0], noise[0],
                                slcthis, logfile ):
                            return False
                    else:
                        print('No geotiff file found for subswath {0} in '\
                        'directory{1}. Trying other subswaths.'.format( sw,
                                safedir ))
                        return False
                else:
                    print('No geotiff file found for subswath {0} in '\
                    'directory{1}. Trying other subswaths.'.format( sw, safedir ))
                    return False
        elif acqMode == 'sm':
            tiff = glob(
                os.path.join( safedir, 'measurement',
                   's1*-slc-vv-*.tiff')
                )
            annot = glob(
                    os.path.join( safedir, 'annotation',
                        's1*-slc-vv-*.xml')
                    )
            calib = glob(
                    os.path.join( safedir, 'annotation', 'calibration',
                        'calibration-s1*-slc-vv-*.xml')
                    )
            noise = glob(
                    os.path.join( safedir, 'annotation', 'calibration',
                        'noise-s1*-slc-vv-*.xml')
                    )
            # 10/2021: noise in SM files causes error in par_S1_SLC!!! we didn't check the reason, just avoiding it
            noise = ['-']
            print('CAREFUL - we have removed correction of thermal noise from Stripmap data, as this was causing errors')
            slcthis = os.path.join( imdirthis,
                    imdate.strftime( '%Y%m%d' ) + '.slc' )
            logfile  = os.path.join( logdir,
                    'par_S1_SLC.log' )
            if len(tiff) > 0:
                if os.path.exists( tiff[0] ):
                    if not par_S1_SLC( tiff[0], annot[0], calib[0], noise[0],
                            slcthis, logfile, acqMode='sm' ):
                        return False
                else:
                    print('No geotiff file found in '\
                    'directory{1}.'.format( safedir ))
                    return False
            else:
                print('No geotiff file found in '\
                'directory{1}.'.format( safedir ))
                return False
############################################################ Update file 2 jobs 
#                                                            database
    # All checks confirmed and fields are found, so populated the file2jobs table
    # with the file list. Send a list of files to the DB to be inserted into 
    # the files2jobs table, linking job_id to each file id.
    if job_id != -1:
        licsQuery.set_files2jobs( job_id, filelist )
    return True

################################################################################
#Parse slc tab function
################################################################################
def parse_slc_tab( slctab ):
    """
    Extracts the .slc, .slc_pat and .TOP_par files from slctab
    """
    with open( slctab ) as f:
        slc, slc_par, tops_par = f.read().strip().split( ' ' )
    return slc, slc_par, tops_par

################################################################################
#Check missing bursts function
################################################################################
def check_missing_bursts( burstlist, missingbursts ):
    """
    Checks if missing bursts are critical (in the middle of a frame). If the
    bursts are critical returns True, otherwise the bursts are non-critical (at
    the edge of a frame) and returns false.
    """
    result = True
    swathlist = set([ mb[0][4:7] for mb in missingbursts ])
    for sw in swathlist:
        swathmissinglist = [ mb[0] for mb in missingbursts if sw in mb[0] ]
        swathmissinglist.sort()
        swathburstlist = [ b[0] for b in burstlist if sw in b[0] ]
        swathburstlist.sort()
        missingix = []
        for mb in swathmissinglist:
            missingix.append( swathburstlist.index( mb ) )
        test = 0
        while test in missingix:
            missingix.pop( 0 )
            test += 1
        test = len(swathburstlist) - 1
        while test in missingix:
            missingix.pop()
            test -= 1
        if len(missingix) > 0:
            result = False
    return result


def check_bursts_file(burstlist, filelist, lq):
    blist = []
    filelist2 = []
    for b in burstlist:
        blist.append(b[0])
    for filee in filelist:
        fid=filee[1]
        brsts = lq.get_bursts_in_file(fid)
        brsts = lq.sqlout2list(brsts)
        isok = False
        for b in brsts:
            if b in blist:
                isok = True
        if isok:
            filelist2.append(filee)
        else:
            print('Warning - a file seems not overlap with bursts. Removing')
    return filelist2


################################################################################
#Make frame image function
################################################################################
def make_frame_image( date, framename, burstlist, procdir, licsQuery,
        job_id=-1, acqMode='iw', autodownload = False, test_crosspol = False):
    """ 
    Process the files for the given date
    In:
        date        Timestamp object with acquisition date (but some scripts send datetime.date...)
        framename   name of the processing frame
        burstlist   list of burst ids -------- OBSOLETE - NOT USED HERE
        procdir     path to processing directory
        acqMode     Acquisition mode: 'iw' (Interferometric wide swath)  
                    or 'sm' (Stripmap)
        test_crosspol if True, extract only cross-pol data (for testing only now)
    Out:
        return code 0 Ok
                    1 Problem during file unzipping/reading
                    2 Problem during burst extraction/merging
                    3 Problem during merging of bursts

    This functions works by building up each swath from multiple
    bursts. It then mosiacs these swathes together into a single 
    frame.
    """
############################################################ Pepare file/folders
    #will make date_date as type datetime.date and date as datetime (sadly mess..)
    #print('debug: date is of type: '+str(type(date)))
    if type(date) is not type(dt.datetime.now().date()):
        date_date = date.date()
    else:
        date_date = date
        date = dt.datetime.fromordinal(date.toordinal())
    #print('debug: after the change, date is of type: '+str(type(date)))
    slcdir = os.path.join( procdir, 'SLC' )
    imdir = os.path.join( slcdir, date.strftime( '%Y%m%d' ) )
    # Get all files containing frame bursts on current date
    # and +-1 day (midnight error)
    t1 = date-dt.timedelta(days=1)
    t2 = date+dt.timedelta(days=1)
    filelist1 = licsQuery.get_frame_files_date( framename, t1 )
    filelist = licsQuery.get_frame_files_date( framename, date )
    filelist1 = filelist1 + licsQuery.get_frame_files_date( framename, t2 )
    fl = list( filelist )
    for f in filelist1:
        if not f in fl:
            fl.append(f)
    filelist = tuple( fl )
    # check if they have correct bursts?
    # not working.... because licsQuery is batchDBquery...yikes
    #filelist = check_bursts_file(burstlist, filelist, licsQuery)
    # if abs_filepath has a metadataonly zip file, modify the filepath to remove
    # this part of the string to point at where the abs_filepath should actually
    # be.
    fl = list( filelist )
    for idx in range ( 0, len( fl ) ):
        l = list( fl[ idx ] )
        l[2] = l[2].replace( '.metadata_only.', '.' )
        fl[ idx ] = tuple( l )
    filelist = tuple( fl )
    #check for duplicites:
    names = set()
    for i in range(len(filelist)):
        names.add(filelist[i][1][0:62])
    if len(names) < len(filelist):
        print('a duplicite was found')
        filelist2 = []
        for name in names:
            pom = 0
            #filep = []
            for filea in filelist:
                if name == filea[1][0:62]:
                    pom = pom +1
                    #filep.append(filea[2])
            if pom == 0:
                for idx in range(len(filelist)):
                    if name == filelist[idx][1][0:62]:
                        filelist2.append(filelist[idx])
            else:
                for idx in range(len(filelist)):
                    if name == filelist[idx][1][0:62]:
                        if os.path.exists(filelist[idx][2]):
                            filelist2.append(filelist[idx])
                            break
        if len(names) > len(filelist2):
            print('some file is not existing. cancelling')
            return 2
        filelist = filelist2
    #raise Usage("DEBUG")
    if autodownload:
        try:
            xfcpath = os.environ['XFCPATH']
            outdir = os.path.join(xfcpath,'SLC')
            #if os.environ['USER']=='earmla':
            #    outdir = '/work/xfc/vol5/user_cache/earmla/SLC'
            if not os.path.exists(outdir):
                outdir = os.environ['LiCSAR_SLC']
        except:
            outdir=os.environ['LiCSAR_SLC']
        #
        i = -1
        #somebody likes tuples.. i dont. at least convert to list of lists
        flist = []
        for f in filelist:
            flist.append(list(f))
        filelist = flist
        for f in filelist:
            i = i+1
            if not os.path.exists(f[2]):
                print('downloading '+f[1])
                filename=f[1]+'.zip'
                rc = s1.download_asf(filename, slcdir = outdir, ingest = True)
                newpath = os.path.join(outdir, filename)
                if not os.path.exists(newpath):
                    print('ERROR downloading file needed for initialisation, cancelling')
                    return 2
                # change the record in the filelist ... as list... NOT as tuples..
                filelist[i][2] = newpath
    
############################################################ Build Frame
    if read_files( filelist, slcdir, date, procdir, licsQuery, job_id, acqMode, test_crosspol ):
        # Only do if read_files does not return False, i.e. hits
        # a snag
        # Remove unzipped SAFE directories
        os.system( 'rm -rf {0}/*.SAFE'.format( 
                    os.path.join( imdir ) 
                ) 
            )
        tabdir = os.path.join( procdir, 'tab' )
        if not os.path.exists( tabdir ):
            os.mkdir( tabdir )
        # do the old-IPF correction here, before any other operations (as merging, cropping etc.) (ML, 2019)
        # however right now this will work only in case we run standard processing chain, using licsinfo db
        for f in filelist:
            fullname=f[1]
            if licsQuery.get_ipf(fullname)=='002.36':
                #print('we would normally correct for old IPF version data here', file=sys.stdout)
                print('Correcting for old IPF version data', file=sys.stdout)
                shortname=fullname.split( '_' )[5]
                SLC_tmp = os.path.join( imdir, '{0}.{1}.tmp.slc'.format(shortname, 'IW1'))
                SLC_ok = os.path.join( imdir, '{0}.{1}.slc'.format(shortname, 'IW1'))
                shutil.move(SLC_ok, SLC_tmp)
                shutil.move(SLC_ok + '.par', SLC_tmp + '.par')
                logfilename = os.path.join( procdir, 'log', 
                        'phase_shift_{0}.log'.format( date_date.strftime( '%Y%m%d' ) ) )
                if not SLC_phase_shift(SLC_tmp, SLC_tmp + '.par', SLC_ok, SLC_ok + '.par', -1.25, logfilename):
                    print('Something went wrong correcting for old IPF version data. Log file {0}'.format(logfilename), file=sys.stderr)
                    return 3
                os.remove(SLC_tmp)
                os.remove(SLC_tmp + '.par')
            
        if acqMode == 'iw':
            if len( filelist ) > 1:
                # bursts are in 2 or more file, copy necessary bursts and merge
                print('Bursts are distributed over more than 1 file, extracting '\
                    'bursts from files and merging...')
                burstnolist = licsQuery.get_burst_no( framename, date )
                # 2022-06 update: also try for midnight error (otherwise some bursts may not be found!!!), just this rough way:
                try:
                    burstnolist += licsQuery.get_burst_no( framename, t1 )
                except:
                    print('')
                try:
                    burstnolist += licsQuery.get_burst_no( framename, t2 )
                except:
                    print('')
    ############################################################ Sweep through swathes
                    #sw = IW1,IW2, etc.
                for sw in sorted( 
                        list( 
                            set( [ sw[0].split( '_' )[1] for sw in burstnolist ] ) 
                            ) 
                        ):
                    fileset = [ f[1].split( '_' )[5] for f in filelist ] #build a working
                    #list of files containing bursts
                    fileset.sort()
                    fileset2 = copy.deepcopy( fileset )
    ############################################################ loop through files 
    #                                                            and strip out relevant
    #                                                            bursts
                    for filethis in fileset:
                        burstnolistthis = [ 
                                e[2] + 1 for e in burstnolist 
                                if filethis in e[1] and sw in e[0] 
                                ]
                        if burstnolistthis: #Maybe no bursts in this subswath for frame...
                            burstnolistthis.sort()
                            filename = os.path.join( imdir, filethis )
                            filetab = os.path.join( tabdir, '{0}_tab'.format( 
                                filethis ) )
                            rc, msg = make_SLC_tab( filetab, filename + '.slc', 
                                    [sw] ) 
                                        #Input tab file -> specifies source SLC
                            if rc > 0:
                                print('\nProblem creating SLC '\
                                                    'tab{0} for date {1}. Error '\
                                                    'message:'\
                                                    '\n {2}'\
                                                    '\nContinuing with next '\
                                                    'date.'.format( filetab, 
                                                            date, msg ), file=sys.stderr)
                                return 2 
                            temptab = os.path.join( tabdir, '{0}_tmp_tab'.format(
                                filethis 
                                ))
                            rc, msg = make_SLC_tab( temptab, 
                                    filename + '_crop.slc', [sw] )
                            #Output tab file -> where we put our stripped bursts
                            if rc > 0:
                                print('\nProblem creating temporary '\
                                                    'SLC tab {0} for date {1}. '\
                                                    'Error message:\n {2}'\
                                                    '\nContinuing with next '\
                                                    'date.'.format( temptab, date, 
                                                            msg ), file=sys.stderr)
                                return 2
                            bursttab = os.path.join( tabdir,
                                    '{0}_burst_tab'.format( filethis ) )
                            rc, msg = make_burst_tab( bursttab,
                                    burstnolistthis[0], burstnolistthis[-1] )
                            if rc > 0:
                                print('\nProblem creating burst '\
                                                    'tab {0} for date {1}. Error '\
                                                    'message:'\
                                                    '\n {2}'\
                                                    '\nContinuing with next '\
                                                    'date.'.format( bursttab, 
                                                            date, msg ), file=sys.stderr)
                                return 2
                            copylogfile = os.path.join( procdir, 'log', 
                                    'SLC_copy_S1_TOPS_{0}.log'.format( 
                                        filetab.split( '/' )[-1] ) 
                                    )
                # Copy relevent bursts from source slc to new slc (crop)
                            if SLC_copy_S1_TOPS( filetab, temptab, bursttab,
                                    imdir, procdir, copylogfile ):
                                print('\nProblem copying bursts '\
                                                    'for swath {0}. Continuing '\
                                                    'with next date.'.format( sw ), file=sys.stderr)
                                return 2
                            else:
                                rename_slc( temptab, filetab ) # if successful move
                                #_crop.slc to old slc name
                        else:
                #if slc file is not relevent remove from our working list
                            fileset2.remove( filethis )
                    fileset = copy.deepcopy( fileset2 ) # get working file list with 
                                                    # redundant files removed
    ############################################################ Create swathe slc file
                    #start with the first slc file (at least 1)
                    filetab = os.path.join( tabdir, '{0}_tab'.format( fileset[0] ) ) 
                    #swathe slc file
                    slctab = os.path.join( tabdir,
                            '{0}_tab'.format( fileset[0].split( 'T' )[0] )
                            ) 
                    slcname = os.path.join( imdir, fileset[0].split( 'T' )[0] )
                    rc,msg = make_SLC_tab( slctab, slcname+'.slc', [ sw ] ) 
                    if rc > 0:
                        print('\nProblem creating SLC tab {0} for '\
                                            'date {1}. Error message:'\
                                            '\n {2}'\
                                            '\nContinuing withnext date.'.format( 
                                                    slctab, date, msg ), file=sys.stderr)
                        return 2
                    rename_slc( filetab, slctab )#first slc is our start point
                    with cd( procdir ):
                        padcall = 'pad_SLCs {0} {1} {2}'.format(
                                date.strftime( '%Y%m%d' ), sw[-1] , sw[-1]
                                )
                        os.system( padcall ) # pad slc file
                    if len( fileset ) > 1: #there are more files containing bursts
                        for filethis in fileset[1:]: #loop through the remaining slc files
                            filetab = os.path.join( tabdir,
                                    '{0}_tab'.format( filethis )
                                    )
                            tempfile = slcname + '_merged'
                            rc, msg = make_SLC_tab( temptab, tempfile + '.slc', 
                                [ sw ] )
                            if rc > 0:
                                print('\nProblem creating SLC '\
                                                    'tab{0} for date {1}. Error '\
                                                    'message:'\
                                                    '\n {2}'\
                                                    '\nContinuing with next '\
                                                    'date.'.format( temptab, date,
                                                            msg ), file=sys.stderr)
                                return 2
                            logfile = os.path.join( procdir, 'log',
                                    'SLC_cat_S1_TOPS_{0}_{1}.log'.format( sw,
                                        filetab.split( '/' )[-1] )
                                    )
                            if not SLC_cat_S1_TOPS( slctab, filetab, temptab, 
                                    logfile ): # concat our swath slc file 
                                                    # with this slc file -> merged
                                print('\nProblem concatenating '\
                                                    'bursts in subswath {0}. Log '\
                                                    'file {1}. Continuing with '\
                                                    'next acquisition '\
                                                    'date.'.format( sw, logfile ), file=sys.stderr)
                                return 2
                            rename_slc( temptab, slctab ) # replace our swathe slc file
                                                    # with this new, longer slc file
                    else: # only one file in this swathe -> code below redundant?
                        filethis = fileset[0]
                        filename = os.path.join( imdir, filethis )
                        filetab = os.path.join( tabdir, 
                                '{0}_tab'.format( filethis ) 
                                )
                        rc, msg = make_SLC_tab( filetab, filename + '.slc', [ sw ] )
                        if rc > 0:
                            print('\nProblem creating SLC tab {0} '\
                                                'for date {1}. Error message:'\
                                                '\n {2}'\
                                                '\nContinuing with next '\
                                                'date.'.format( filetab, date,
                                                        msg ), file=sys.stderr)
                            return 2
    ############################################################ Mosaic Swath SLCs 
                                                            # into single frame
                swathlist = [ sw for sw in ['IW1','IW2','IW3']
                            if os.path.exists(os.path.join(imdir,
                                '{0}.{1}.slc'.format( 
                                    date.strftime( '%Y%m%d' ), sw )
                                    )
                                )
                            ]
                print('Mosaicing subswaths...')
                tabname = os.path.join( procdir, 'tab', 
                        date.strftime( '%Y%m%d' ) + '_tab' )
                filename = os.path.join( imdir, date.strftime( '%Y%m%d' ) )
                make_SLC_tab( tabname, filename + '.slc', swathlist ) #tabfile for mosaic 
                                                                #instruction, lists 
                                                                # input slc's
                logfilename = os.path.join( procdir, 'log', 
                        'mosaic_TOPS_{0}.log'.format( 
                            date.strftime( '%Y%m%d' ) 
                            ) 
                        )
                if not SLC_mosaic_S1_TOPS( tabname, filename + '.slc', gc.rglks, 
                        gc.azlks, logfilename ): # mosaic the SLC's
                    print('Something went wrong mosaicing '\
                                        'subswaths together. Log file {0}. '\
                                        'Continuing with next acquisition '\
                                        'date.'.format( logfilename ), file=sys.stderr)
                    return 3
                logfilename =  os.path.join( procdir, 'log',
                                            'multilookSLC_{0}.log'.format(
                                                date.strftime( '%Y%m%d' ) 
                                                )
                                            )
    ############################################################ Mulltilook 
                multicall = 'multilookSLC {0} {1} {2} 1 {3} &> {4}'.format(
                        date.strftime( '%Y%m%d' ), gc.rglks, gc.azlks, imdir, 
                        logfilename )
                rc = os.system( multicall )
                if rc != 0:
                    print('Something went wrong multilooking the '\
                                        'merged image. Log file {0}. Continuing '\
                                        'with next acquisition '\
                                        'date.'.format( logfilename ), file=sys.stderr)
                    return 3
    ############################################################ Get orbit files
                # Temporary code to handle the logging to a seperate log file
                logfilename = os.path.join( procdir, 'log', 
                        'getValidOrbFile_{0}.log'.format( date.strftime( '%Y%m%d' ) 
                            ) 
                        )
                fileHan = logging.FileHandler(logfilename)
                formatter = logging.Formatter(
                                '%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
                fileHan.setFormatter(formatter)
                logger.addHandler(fileHan)
                logger.setLevel(logging.DEBUG)
                print('Updating orbit files...')
                for zipFile in glob(imdir+'/*.zip'):
                    #Loop through zipfiles and get valis orbit file
                    print("Updating orbit for {0}".format(zipFile))
                    mtch = re.search('.*(S1[ABCD]).*',zipFile)
                    sat = mtch.groups()[0]
                    localOrbDir = get_orb_dir(sat)
                    try:
                        orbit = getValidOrbFile(localOrbDir,zipFile)
                        orbdone = True
                        slcOrbit = imdir+"/"+os.path.basename(orbit)
                        if not os.path.lexists(imdir+"/"+os.path.basename(orbit)):
                            #symlink as not always on same physical device
                            os.symlink(orbit,slcOrbit)
                    except:
                        print('error during getting orbit file')
                        orbdone = False
                logger.removeHandler(fileHan)
                if orbdone:
                    logfilename = os.path.join( procdir, 'log', 
                        's1_opod_vec_{0}.log'.format( date.strftime( '%Y%m%d' ) 
                            ) 
                        )
                    for parFile in glob(imdir+"/*.sl*.par"):
                        print("applying orbit correction to {0}".format(parFile))
                        S1_OPOD_vec(parFile,slcOrbit,logfilename)
                else:
                    print('ERROR: no orbit files available, continuing using only predicted orbits')
                    #return 2
            else:
    ############################################################ Special case of singular file
                # bursts are in only 1 file, just copy necessary
                # bursts
                burstnolist = licsQuery.get_burst_no( framename, date )
                filethis = filelist[0][1].split( '_' )[5]
                filetab = os.path.join( tabdir, '{0}_tab'.format( filethis ) )
                filename = os.path.join( imdir, filethis )
    ############################################################ Loop through swathes
                for sw in sorted( 
                        list( 
                            set([ sw[0].split( '_' )[1] for sw in burstnolist ])
                            )
                        ):
                    rc, msg = make_SLC_tab( filetab, filename + '.slc', [ sw ] )
                    if rc > 0:
                        print('\nProblem creating SLC tab {0} for '\
                                            'date {1}. Error message:'\
                                            '\n {2}'\
                                            '\nContinuing with next '\
                                            'date.'.format( filetab, date, msg ), file=sys.stderr)
                        return 2
                    slctab = os.path.join( tabdir, 
                            '{0}_tab'.format( filethis.split( 'T' )[0] ) 
                            )
                    slcname = os.path.join( imdir, filethis.split( 'T' )[0] )
                    rc, msg = make_SLC_tab( slctab, slcname + '.slc', [ sw ] )
                    if rc > 0:
                        print('\nProblem creating SLC tab {0} for '\
                                            'date {1}. Error message:'\
                                            '\n {2}'\
                                            '\nContinuing withnext '\
                                            'date.'.format( slctab, date, msg ), file=sys.stderr)
                        return 2
                    temptab = os.path.join( tabdir, '{0}_tmp_tab'.format(filethis) )
                    rc, msg = make_SLC_tab( temptab, filename + '_crop.slc',
                            [ sw ] )
                    if rc > 0:
                        print('\nProblem creating SLC tab {0} for '\
                                            'date {1}. Error message:'\
                                            '\n {2}'\
                                            '\nContinuing withnext '\
                                            'date.'.format( filetab, date, msg ), file=sys.stderr)
                        return 2
                    burstnolistthis = [ e[2]+1 for e in burstnolist
                            if filethis in e[1] and sw in e[0]
                            ]
                    burstnolistthis.sort()
                    bursttab = os.path.join( tabdir, 
                            '{0}_burst_tab'.format( filethis ) )
                    rc, msg = make_burst_tab( bursttab, burstnolistthis[0],
                            burstnolistthis[-1] )
                    if rc > 0:
                        print('\nProblem creating burst tab {0} '\
                                            'for date {1}. Error message:'\
                                            '\n {2}'\
                                            '\nContinuing withnext '\
                                            'date.'.format( bursttab, date, msg ), file=sys.stderr)
                        return 2
                    copylogfile = os.path.join( procdir, 'log',
                                            'SLC_copy_S1_TOPS_{0}.log'.format(
                                                filetab.split('/')[-1]
                                                )
                                            )
    ############################################################ Strip out bursts
                                                            # for this swathe
                    if SLC_copy_S1_TOPS( filetab, temptab, bursttab, imdir, 
                            procdir, copylogfile ):
                    # if SLC_copy_S1_TOPS(filetab,temptab,burstnolistthis[0],
                    #burstnolistthis[-1],imdir,procdir,copylogfile):
                        print('\nProblem copying bursts for '\
                                            'swath{0}. Continuing with next '\
                                            'date.'.format( sw ), file=sys.stderr)
                        return 2
                    else:
                        rename_slc( temptab, slctab )
    ############################################################ Mosaic Swathes together
                swathlist = [ sw for sw in [ 'IW1', 'IW2', 'IW3' ] 
                            if os.path.exists(
                                os.path.join( imdir, '{0}.{1}.slc'.format( 
                                        date.strftime('%Y%m%d'), sw 
                                        )
                                    )
                                )
                            ]
                print('Mosaicing subswaths...')
                tabname = os.path.join( procdir, 'tab', 
                        date.strftime( '%Y%m%d' ) + '_tab' )
                filename = os.path.join( imdir, date.strftime( '%Y%m%d' ) )
                make_SLC_tab( tabname, filename + '.slc', swathlist )
                logfilename = os.path.join( procdir, 'log', 
                        'mosaic_TOPS_{0}.log'.format( date.strftime( '%Y%m%d' ) )
                        )
                # mosaic function
                if not SLC_mosaic_S1_TOPS( tabname, filename + '.slc', gc.rglks,
                        gc.azlks, logfilename ):
                    print('Something went wrong mosaicing '\
                                        'subswaths '\
                                        'together. Log file {0}. Continuing with '\
                                        'next acquisition '\
                                        'date.'.format( logfilename ), file=sys.stderr)
                    return 3
                logfilename =  os.path.join( procdir, 'log', 
                        'multilookSLC_{0}.log'.format( date.strftime( '%Y%m%d' ) ) 
                        )
    ############################################################ Multilook
                multicall = 'multilookSLC {0} {1} {2} 1 {3} &> {4}'.format(
                        date.strftime( '%Y%m%d' ), gc.rglks, gc.azlks, imdir,
                        logfilename )
                rc = os.system( multicall )
                if rc != 0:
                    print('Something went wrong multilooking the '\
                                        'merged image. Log file {0}. Continuing '\
                                        'with next acquisition '\
                                        'date.'.format( logfilename ), file=sys.stderr)
                    return 3
    ########################################################### Update orbit files
                #Setup logging for the orbit library
                fileHan = logging.FileHandler(logfilename)
                formatter = logging.Formatter(
                                '%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
                fileHan.setFormatter(formatter)
                logger.addHandler(fileHan)
                logger.setLevel(logging.DEBUG)
                print('Updating orbit files...')
                for zipFile in glob(imdir+'/*.zip'):
                    #Loop through zipfiles and get valis orbit file
                    print("Updating orbit for {0}".format(zipFile))
                    mtch = re.search('.*(S1[ABCD]).*',zipFile)
                    sat = mtch.groups()[0]
                    localOrbDir = get_orb_dir(sat)
                    orbit = getValidOrbFile(localOrbDir,zipFile)
                    if orbit:
                        orbdone = True
                        slcOrbit = imdir+"/"+os.path.basename(orbit)
                        if not os.path.lexists(imdir+"/"+os.path.basename(orbit)):
                            #symlink as not always on same physical device
                            os.symlink(orbit,slcOrbit)
                    else:
                        print('error during getting orbit file')
                        orbdone = False
                logger.removeHandler(fileHan)
                if orbdone:
                    for parFile in glob(imdir+"/*.sl*.par"):
                        print("applying orbit correction to {0}".format(parFile))
                        S1_OPOD_vec(parFile,slcOrbit,logfilename)
                else:
                    print('ERROR: no orbit files available, continuing using only predicted orbits')
                    #return 2
        else:
            logfilename = os.path.join( procdir, 'log', 
                    '????.log'.format( date.strftime( '%Y%m%d' ) )
                    )
            ########################################################### Update orbit files
            #Setup logging for the orbit library
            fileHan = logging.FileHandler(logfilename)
            formatter = logging.Formatter(
                            '%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
            fileHan.setFormatter(formatter)
            logger.addHandler(fileHan)
            logger.setLevel(logging.DEBUG)
            print('Updating orbit files...')
            for zipFile in glob(imdir+'/*.zip'):
                #Loop through zipfiles and get valis orbit file
                print("Updating orbit for {0}".format(zipFile))
                mtch = re.search('.*(S1[ABCD]).*',zipFile)
                sat = mtch.groups()[0]
                localOrbDir = get_orb_dir(sat)
                try:
                    orbit = getValidOrbFile(localOrbDir,zipFile)
                    orbdone = True
                    slcOrbit = imdir+"/"+os.path.basename(orbit)
                    if not os.path.lexists(imdir+"/"+os.path.basename(orbit)):
                        #symlink as not always on same physical device
                        os.symlink(orbit,slcOrbit)
                except:
                    print('error during getting orbit file')
                    orbdone = False
            logger.removeHandler(fileHan)
            if orbdone:
                for parFile in glob(imdir+"/*.sl*.par"):
                    print("applying orbit correction to {0}".format(parFile))
                    S1_OPOD_vec(parFile,slcOrbit,logfilename)
            else:
                print('ERROR: no orbit files available, cancelling for stripmap as we want the best here')
                return 2
            # Multilooking
            multicall = 'multilookSLC {0} {1} {2} 1 {3} &> {4}'.format(
                date.strftime('%Y%m%d'), gc.rglks, gc.azlks, imdir,
                logfilename)
            rc = os.system(multicall)
            if rc != 0:
                print('Something went wrong multilooking'.format(logfilename), file=sys.stderr)
                return 3
    else:
############################################################ Failed to process this date
        # One of the read files failed, continue with next date
        print('Could not read all files correctly, continuing '\
                             'with next acquisition date.', file=sys.stderr)
        shutil.rmtree( imdir )
        return 1
    return 0
