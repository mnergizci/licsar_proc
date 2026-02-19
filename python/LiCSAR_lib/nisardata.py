#!/usr/bin/env python

import os
import datetime as dt
# from sentinelsat.sentinel import SentinelAPI # this was beautiful toolbox, sadly changed to CDSE..
import re
import pandas as pd
import requests
#import arch2DB
#here is the nostdout function:
from LiCSAR_misc import *
import asf_search as asf

'''
# SciHub is gone - sentinelsat not updated
def download(uuid, slcdir):
    scihub_user, scihub_pass, scihub_url = get_scihub_creds()
    scihub = SentinelAPI(scihub_user, scihub_pass, scihub_url)
    rc = scihub.download(uuid, slcdir)
    return rc
'''



# first get some results e.g. as
results=asf.search(dataset='NISAR', processingLevel='GSLC')  # or 'GUNW'
# then get session and download:
asf_session = get_asf_session()
results.download(path='.', session=asf_session)   # tested - works ok

def download(filename, slcdir = '/gws/nopw/j04/nceo_geohazards_vol2/LiCS/temp/SLC', ingest = False, provider='cdse'):
    '''wrapper to wget commands. the provider must be one of ['cdse', 'alaska']
    '''
    # slcdir = os.environ['LiCSAR_SLC']
    wgetpath = os.environ['LiCSARpath']+'/bin/scripts/wget_'+provider
    cmd = 'cd {0}; {1} {2}'.format(slcdir, wgetpath, filename)
    rc = os.system(cmd)
    filepath = os.path.join(slcdir,filename)
    if ingest:
        os.system('arch2DB.py -f '+filepath)
    return filepath

def search_alaska(frame, footprint, startdate, enddate, sensType = 'IW'):
    print('performing data discovery using ASF server')
    track = int(frame[0:3])
    trackpre=abs(track-1)
    trackpost=track+1
    tracks = [trackpre, track, trackpost]
    #strtrack = str(trackpre)+'-'+str(trackpost)
    ascdesc = frame[3]
    if ascdesc == 'D': ascdesc = 'DESCENDING'
    if ascdesc == 'A': ascdesc = 'ASCENDING'
    #url = 'https://api.daac.asf.alaska.edu/services/search/param?platform=S1&processingLevel=SLC&output=JSON'
    #url = url+'&relativeOrbit='+strtrack
    #url = url+'&beamMode='+sensType
    #url = url+'&start={0}&end={1}'.format(startdate.strftime('%Y-%m-%d'),enddate.strftime('%Y-%m-%d'))
    #url = url + '&flightDirection='+ascdesc
    #url = url + '&intersectsWith='+footprint
    #r = requests.get(url)
    # or using asf search:
    r = asf.geo_search(relativeOrbit=tracks, beamMode=sensType,
                   start = startdate, end = enddate,
                   flightDirection=ascdesc, intersectsWith=footprint,
                   platform='S1', processingLevel='SLC')
    images = []
    for gg in r:
        images.append(gg.properties['sceneName'])
    #df = pd.DataFrame.from_dict(r.json()[0])
    #return df
    return images



def get_epochs_for_frame(frame, startdate = dt.datetime.strptime('20141001','%Y%m%d').date(), enddate = dt.date.today(), returnAsDate = False):
    new_images = get_images_for_frame(frame, startdate, enddate)
    epochs = [i.split('_')[5].split('T')[0] for i in new_images]
    epochs = list(set(epochs))
    if returnAsDate:
        return [dt.date(int(a[:4]),int(a[4:6]),int(a[6:8])) for a in epochs]
    else:
        return epochs


def get_images_for_footprint(frameName, footprint, startdate = dt.datetime.strptime('20141001','%Y%m%d').date(),
                         enddate = dt.date.today(), sensType = 'IW'):
    '''frameName can be a fake one, e.g. '018D' is enough. footprint is a POLYGON WKT, e.g.
    bidsgpd = fc.bursts2geopandas([burstid])
    footprint = bidsgpd.geometry[0].wkt
    '''
    images = search_alaska(frameName, footprint, startdate, enddate, sensType)
    return images


def get_images_for_frame(frameName, startdate = dt.datetime.strptime('20141001','%Y%m%d').date(),
             enddate = dt.date.today(), sensType = 'IW', outAspd = False, asf = True):
    ''' Will get filenames from CDSE and ASF for the frame. Note this is based on frame polygon, overlapping bursts might cause issues!

    Args:
        frameName: str
        startdate: dt.date
        enddate: dt.date
        sensType: 'IW' or 'SM'
        outAspd: if True, it will use only CDSE (skip ASF) and return the outputs as more complete pd.DataFrame
        asf: would use ONLY ASF (will avoid CDSE) for the search (does not include everything...), otherwise CDSE+ASF (or purely CDSE in case of outAspd==True)

    Returns:
        list or pd.DataFrame
    '''
    #startdate and enddate should be of type datetime.date (but datetime may also work)
    # problem is that only full days are selected, no search by time
    if str(type(startdate)).split("'")[1] == 'str':
        startdate = dt.datetime.strptime(startdate,'%Y%m%d').date()
    if str(type(enddate)).split("'")[1] == 'str':
        enddate = dt.datetime.strptime(enddate,'%Y%m%d').date()
    #one extra date needed for scihub:
    enddate = enddate + dt.timedelta(days=1)
    if enddate > (dt.date.today() - dt.timedelta(days=1)):
        asf = False
        print('checking the latest data - using only CDSE')
        #print('SHOULD DO FROM CDSE - keeping ASF for now, no data for last 24(or 48?) hours') 
    #check/update sensType
    if sensType == 'IW':
        if frameName.split('_')[1]=='SM':
            print('the frame is a stripmap')
            sensType = 'SM'
    #nmax = 100
    import LiCSquery as lq
    footprint = lq.get_wkt_boundaries(frameName)
    ascdesc = frameName[3]
    if ascdesc == 'D': ascdesc = 'DESCENDING'
    if ascdesc == 'A': ascdesc = 'ASCENDING'
    track = int(frameName[0:3])
    #startdate = dt.datetime.strptime(startdate,'%Y%m%d').date()
    result = None
    images = None
    track1=track-1
    track2=track+1
    if track2 == 176:
        track2 = 1
    if track1 == 0:
        track1 = 175
    if outAspd or not asf:
        # 2023-11-06 - searching through CDSE, solution by Manu Delgado Blasco (many thanks!) https://github.com/sentinelsat/sentinelsat/issues/583
        # cannot find docs for OData! e.g. - use of 'sensoroperationalMode' ends by Invalid field: sensoroperationalMode (BUT WHAT ARE VALID FIELDS????)
        topp = 400 # max 1000   ### 2023-11-16 fix
        cdsequery = f"https://catalogue.dataspace.copernicus.eu/odata/v1/Products?$filter=Collection/Name eq 'SENTINEL-1' and " \
        "OData.CSC.Intersects(area=geography'SRID=4326;{0}') and ContentDate/Start gt {1}T00:00:00.000Z and ContentDate/Start lt {2}T00:00:00.000Z " \
        "and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq 'SLC') " \
        "and (Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'relativeOrbitNumber' and att/OData.CSC.IntegerAttribute/Value eq {3})" \
        " or Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'relativeOrbitNumber' and att/OData.CSC.IntegerAttribute/Value eq {4})" \
        " or Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'relativeOrbitNumber' and att/OData.CSC.IntegerAttribute/Value eq {5})) " \
        "and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'orbitDirection' and att/OData.CSC.StringAttribute/Value eq '{6}') " \
        "and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'operationalMode' and att/OData.CSC.StringAttribute/Value eq '{7}')" \
        "&$top={8}".format(footprint, str(startdate), str(enddate),
            str(track1),str(track),str(track2),
            ascdesc, sensType,
            str(topp)
            )
        json = requests.get(cdsequery).json()
        # for list of params in the new CDSE (THEY ARE NOT PUBLISHED!!!!!!!!!!!!!!!!! in NOV 2023 when SciHub is deactivated!!!!! this is not nice approach from ESA)
        # can be found after 'expanding the metadata', e.g. here:
        # https://catalogue.dataspace.copernicus.eu/odata/v1/Products?%24filter=contains(Name,%27S1A_EW_GRD%27)%20and%20ContentDate/Start%20gt%202022-05-03T00:00:00.000Z%20and%20ContentDate/Start%20lt%202022-05-03T12:00:00.000Z&%24expand=Attributes
        #
        dframe = pd.DataFrame.from_dict(json["value"])
        if dframe.empty:
            print('CDSE: empty output')
            return False
        i = 0
        dframefull = dframe.copy()
        while not dframe.empty:
            i = i+1
            json = requests.get(cdsequery+"&$skip="+str(i*topp)).json()
            dframe = pd.DataFrame.from_dict(json["value"])
            dframefull = pd.concat([dframefull, dframe], ignore_index=True)
        #
        dframefull['title'] = dframefull['Name'].apply(lambda x: x.split('.')[0])
        if outAspd:
            return dframefull
        else:
            images = dframefull['title'].values.tolist()
            # DEBUG: ASF uses a bit different filename. So adding this here, as ASF is used as backup (and I don't know how to search with filename from ASF to do it through wget_alaska.sh
            try:
                print('CDSE search complete, adding also from ASF (as some filenames there differ in the last 4 digits)')
                images += search_alaska(frameName, footprint, startdate, enddate, sensType)
                #images += df['granuleName'].values.tolist()
            except:
                print('error in connection to ASF')
            return list(set(images))
    else:
        try:
            images = search_alaska(frameName, footprint, startdate, enddate, sensType)
            #images = df['granuleName'].values.tolist()
        except:
            print('error searching through ASF, cancelling') #', trying scihub')
            '''
            try:
                scihub_user, scihub_pass, scihub_url = get_scihub_creds()
                scihub = SentinelAPI(scihub_user, scihub_pass, scihub_url)
                result = scihub.query(footprint, date = (startdate.strftime('%Y%m%d'), enddate.strftime('%Y%m%d')), \
                             platformname = 'Sentinel-1', producttype = 'SLC', \
                             relativeorbitnumber = {track1, track, track2}, sensoroperationalmode = sensType, orbitdirection = ascdesc)
                df = scihub.to_dataframe(result)
                images = df['title'].values.tolist()
            except:
                print('error in scihub search, should try CEDA elastic search (no option for detailed search, not using it now..)')
            '''
        #TODO!!
        #from elasticsearch import Elasticsearch
        #query = {
        #    "query": {"match_all": {}}
        #    }
        #es = Elasticsearch(["https://elasticsearch.ceda.ac.uk"])
        #es.search(index="ceda-eo", body=query)
        #result = es.indices.get_mapping(index="ceda-eo")
    #scihub.to_geodataframe(result)
    return images


def get_asf_session():
    credentials = os.path.join(os.environ['HOME'], '.asf_credentials')
    if not os.path.exists(credentials):
        credentials = os.path.join(os.environ["LiCSAR_configpath"],'asf_credentials')
    f = open(credentials,'r')
    asf_user = re.sub('\W+','',f.readline().split('=')[1])
    asf_pass = re.sub('\W+','',f.readline().split('=')[1])
    f.close()
    return asf.ASFSession().auth_with_creds(asf_user, asf_pass)

