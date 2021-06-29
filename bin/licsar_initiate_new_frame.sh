#!/bin/bash
#a script that will generate master, DEM  and all other necessary files to initiate a new frame
#module load licsar_proc #or _testing
curdir=$LiCSAR_procdir

setupmasterextra=''
outres=0.001
r=20
a=4

if [ -z $1 ];
then
 echo "Usage: licsar_initiate_new_frame.sh FRAME [MASTER_YYMMDD] "
 echo "where frame can be e.g. 010D_11058_131313 20180722"
 echo "(if master date is not given, it will choose automatically, from last 3 months data)"
 echo "(to include custom downloaded master files, don't forget to arch2DB.py them first)"
 echo "parameters:"
 echo " -H - do master in highest resolution (r=1, a=1)"
 echo " -D /path/to/dem.tif - use custom DEM - you may want to use gdal_merge.py -a_nodata -32768 .."
 exit
fi

while getopts ":H:D" option; do
 case "${option}" in
  H) a=1; r=1; outres=0.0001; echo "high resolution option enabled"
     ;;
  D) setupmasterextra="-D "$2;
     shift
     ;;
 esac
done
#shift
shift $((OPTIND -1))

if [ ! -z $2 ]; then
 getmaster="-m "$2
 else
 getmaster="-A 1"
fi


 frame=$1

 tr=`echo $frame | cut -d '_' -f1 | sed 's/^0//' | sed 's/^0//' | rev | cut -c 2- | rev`
 rmdir $curdir/$tr/$frame 2>/dev/null
 if [ -d $curdir/$tr/$frame ]; then
  echo "This frame already exists! Stopping here"
  echo "Check and remove(?) "$curdir/$tr/$frame
  exit
 fi
 if [ `echo $frame | grep -o '_' | wc -l` != 2 ]; then
  echo "Wrong frame name. Stopping"
  exit
 fi

mkdir -p $curdir/$tr/$frame
cd $curdir/$tr/$frame
if [ $a == 1 ]; then
     echo "rglks = 1" > local_config.py
     echo "azlks = 1" >> local_config.py
     echo "outres = 0.0001" >> local_config.py
fi

echo "Setting the master image and DEM for frame "$frame
LiCSAR_setup_master.py -f $frame -d $curdir/$tr/$frame $getmaster -r $r -a $a -o $outres $setupmasterextra
if [ ! -d $curdir/$tr/$frame/SLC ]; then
 echo "Something got wrong with the initiation"
 cd - 2>/dev/null
else
 m=`ls SLC`
 if [ ! -d RSLC/$m ]; then 
  mkdir -p RSLC/$m
  for slcfile in `ls $curdir/$tr/$frame/SLC/$m/*`; do ln -s $slcfile `echo $slcfile | sed 's/SLC/RSLC/' | sed 's/slc/rslc/'`; done
 fi
 LiCSAR_05_mk_angles_master
 echo "Generating E-N-U files"
 submit_lookangles.py -f $frame -t $tr
 echo "Generating land mask (would remove heights below 0 m)"
 landmask=$curdir/$tr/$frame/geo/landmask
 hgtgeo=$LiCSAR_public/$tr/$frame/metadata/$frame.geo.hgt.tif
 gmt grdlandmask -G$landmask.tif=gd:GTiff -R$hgtgeo -Df -N0/1/0/1/0
 #gmt grdconvert $landmask.grd $landmask.tif
 #rm $landmask.grd
 cp $landmask.tif $LiCSAR_public/$tr/$frame/metadata/$frame.geo.landmask.tif

#but this is wrong..so fixing.. ugly fast way:
# hgt=$LiCSAR_public/$tr/$frame/metadata/$frame.geo.hgt.tif
# lm=$LiCSAR_public/$tr/$frame/metadata/$frame.geo.landmask.tif
# g=`gmt grdinfo -C $hgt`
# ulx=`echo $g | gawk {'print $2'}`
# uly=`echo $g | gawk {'print $5'}`
# lrx=`echo $g | gawk {'print $3'}`
# lry=`echo $g | gawk {'print $4'}`
# #gdal_translate -of GTIFF -projwin $ulx $uly $lrx $lry $LiCSAR_procdir/GIS/GLDASp4_landmask_025d.nc4 $out
# ncpdq -O -h -a -lat $lm $lm.temp
# rm $lm
# gdal_translate -co COMPRESS=DEFLATE -co PREDICTOR=3 -a_ullr $ulx $uly $lrx $lry -of GTiff -a_srs EPSG:4326 $lm.temp $lm
# rm $lm.temp

 
 echo "Generating master MLI geotiff"
 create_geoctiffs_to_pub.sh -M `pwd` $m
 mkdir -p $LiCSAR_public/$tr/$frame/epochs 2>/dev/null
 mv GEOC.MLI/$m $LiCSAR_public/$tr/$frame/epochs/.
 rmdir GEOC.MLI
 
 echo "Generating public metadata file"
 submit_to_public_metadata.sh $frame
 #sometimes .xy is not generated..
 if [ ! -f $curdir/$tr/$frame/frame.xy ]; then cp $curdir/$tr/$frame/$frame'-poly.txt' $curdir/$tr/$frame/frame.xy; fi
 cp $curdir/$tr/$frame/$frame'-poly.txt' $LiCSAR_public/$tr/$frame/metadata/.
 echo "cleaning"
 rm -f $curdir/$tr/$frame/SLC/*/2*T*.I*sl* 2>/dev/null
 #removing also the mosaic 
 #rm -f $curdir/$tr/$frame/SLC/*/
 rm -f $curdir/$tr/$frame/SLC/*/2???????.slc 2>/dev/null
 echo "done"
fi
