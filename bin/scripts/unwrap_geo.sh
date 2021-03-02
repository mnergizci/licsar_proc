#!/bin/bash
source $LiCSARpath/lib/LiCSAR_bash_lib.sh
#10 is approx coh 0.04
cohthr=10

# M. Lazecky, 2021

if [ -z $2 ]; then
 echo "parameters: frame ifg"
 echo "(if you run it from directory with GEOC/\$ifg, it will use the local files rather than LiCSAR_public)"
 exit
fi
frame=$1
ifgid=$2

track=`track_from_frame $frame`
heredir=`pwd`

if [ -d GEOC/$ifgid ]; then
 echo "using local data in GEOC folder"
 ifgdir=$heredir/GEOC/$ifgid
else
 ifgdir=$LiCSAR_public/$track/$frame/interferograms/$ifgid
fi

#this script will unwrap geocoded data...
#just set those files:
maskfile=$LiCSAR_public/$track/$frame/metadata/$frame.geo.landmask.tif
ifg=$ifgdir/$ifgid.geo.diff_pha.tif
coh=$ifgdir/$ifgid.geo.cc.tif
outunw=$ifgdir/$ifgid.geo.unw.tif

cd $ifgdir
mkdir temp 2>/dev/null

width=`gmt grdinfo $ifg | grep n_columns | rev | gawk {'print $1'} | rev`

#preparing mask.nc
echo "preparing masks"
gmt grdmath $coh 0 NAN 0 GT 0 DENAN = temp/mask.outarea.nc
gmt grdmath $coh 0 NAN $cohthr GT 1 DENAN = temp/mask.inarea.nc #pixel reg!!!! 
#gmt grdedit temp/mask.inarea.nc -T -R$ifg   #to pixel reg
if [ -f $maskfile ]; then
 gmt grdcut -N1 $maskfile -Gtemp/mask.landmask.nc -R$ifg  #grid reg
 gmt grdedit temp/mask.landmask.nc -T -R$ifg   #to pixel reg
 gmt grdmath -N temp/mask.inarea.nc temp/mask.landmask.nc MUL = temp/mask.fullin.nc
 gmt grdmath -N temp/mask.outarea.nc temp/mask.fullin.nc MUL = temp/mask.nc
else
 cp temp/mask.inarea.nc temp/mask.fullin.nc
 cp temp/mask.outarea.nc temp/mask.nc
fi

#gapfilling masked areas
echo "gapfilling masked areas"
#cp temp/mask.nc temp/mask.georeg.nc
#
# ok, masking only the internal parts..
cp temp/mask.fullin.nc temp/mask.fullin.georeg.nc
#gmt grdedit temp/mask.georeg.nc -T -R$ifg   #to pixel reg
gmt grdedit temp/mask.fullin.georeg.nc -T -R$ifg   #to pixel reg
#gmt grdmath -N $ifg temp/mask.fullin.georeg.nc MUL 0 NAN = temp/ifg.fullin.tofill.nc
gmt grdmath -N $ifg 0 NAN 10 DENAN temp/mask.fullin.georeg.nc MUL 0 NAN = temp/ifg.masked.tofill.nc

#gmt grdmath -N $ifg temp/mask.georeg.nc MUL 0 NAN = temp/ifg.masked.nc
#time gmt grdfill temp/ifg.masked.nc -An -Gtemp/pha1.nc
gmt grdfill temp/ifg.masked.tofill.nc -An -Gtemp/pha1.filled.nc
gmt grdmath temp/pha1.filled.nc 10 NAN 0 NAN 0 DENAN = temp/pha1.nc

#make binaries for snaphu:
echo "unwrapping by snaphu"
#input is phase only = snaphu needs phase in 0,2 pi
gmt grdmath temp/pha1.nc PI ADD = temp/pha1.02pi.nc
gmt grd2xyz -ZTLf -bof temp/pha1.02pi.nc > temp/pha1
#convert coh to 0,1
gmt grdmath $coh 255 DIV = temp/coh.nc
gmt grd2xyz -ZTLf -bof temp/coh.nc > temp/coh1
#export mask to 0,1 binary - using only the landmask now..
gmt grd2xyz -ZTLc -bof temp/mask.nc > temp/mask1


#unwrap:
cd temp
cat << EOF > snaphu.conf
STATCOSTMODE  DEFO
INFILEFORMAT  FLOAT_DATA
CORRFILEFORMAT  FLOAT_DATA
OUTFILEFORMAT FLOAT_DATA
RMTMPTILE TRUE
EOF


#time snaphu -f snaphu.conf -M mask1 -o unw1 -c coh1 -g unw1.conncomp pha1 $width #-e est1
time snaphu -f snaphu.conf -M mask1 -o unw1 -c coh1 pha1 $width #-e est1
#now convert back to nc and re-include mask
echo "converting to geotiff"
cat << EOF > unw2nc.py
import numpy as np
import xarray as xr
#
unw1 = np.fromfile('unw1',dtype=np.float32)
mask1 = xr.open_dataset('mask.nc')
a = mask1.copy(deep=True)
unw1 = unw1.reshape(a.z.shape)
unw1 = np.flip(unw1,axis=0)
#
a.z.values = unw1*mask1.z.values
a.z.values[a.z.values==0] = np.nan
a.z.values = a.z.values - np.nanmedian(a.z.values)
a.to_netcdf('unw1.nc')
EOF

python3 unw2nc.py 

#make preview
create_preview_unwrapped unw1.nc 
gmt grdconvert -G$outunw=gd:GTiff unw1.nc
mv unw1png `echo $outunw | rev | cut -c 4- | rev`png
cd ..; rm -r temp
cd $heredir
#echo "now take a look:"
#echo "display unw1.png"

