#!/usr/bin/env python

from __future__ import print_function

import os, sys, glob, argparse
import subprocess as sub
import numpy as np
import netCDF4 as nc

# RC GitLab repo
# git clone git@lex-gitlab.aer.com:RC/common_modules.git
sys.path.append('common_modules')
import utils

# global variables (in CAPS)
MODES = ['garand', 'rfmip']

# LW and SW fields from RRTMGP (Garand) template that will be modified 
NCFIELDSG = ['band_heating_rate', 'band_lims_wvn', 'p_lev', \
  'band_flux_dn', 'band_flux_net', 'band_flux_up', \
  'flux_dn', 'flux_net', 'flux_up', 'heating_rate']

# SW fields from RRTMGP template that will be modified 
NCSWFIELDSG = ['band_flux_dif_dn', 'band_flux_dir_dn', \
  'flux_dif_dn', 'flux_dir_dn']

# LW and SW fields from RFMIP template that will be modified have to
# be determined by input arguments into main()
TOPDIR = '/rd47/scratch/RRTMGP/obsolete/AGU_2017/RRTMG_Run'

# Directory that contains the RRTMGP netCDFs that will be used as a 
# template for the Garand atmospheres
REFNCDIR = '/rd47/scratch/RRTMGP/RRTMGP_SVN/trunk/' + \
  'test/flux_compute/ref'
REFNCLW = '%s/rrtmgp-lw-inputs-outputs-clear.nc' % REFNCDIR
REFNCSW = '%s/rrtmgp-sw-inputs-outputs-clear.nc' % REFNCDIR

class rrtmg():
  def findProfiles(self):
    """
    Extract the RRTMG flux files for given spectral domain
    """

    inFiles = sorted(glob.glob('%s/%s*' % (self.inDir, self.search) ))
    if len(inFiles) == 0: sys.exit('No profiles found, returning')
    self.nProfiles = len(inFiles)

    # some RRTMG files are stored with profile numbers that are not 
    # 0-padded (e.g., OUTPUT_RRTM.GARAND_1 instead of 
    # OUTPUT_RRTM.GARAND_01), so we need to try and address this
    if self.profiles == 'garand':
      profNum = np.array(\
        [int(prof.split('_')[-1]) for prof in inFiles])
      iSort = np.argsort(profNum)
      outFiles = np.array(inFiles)[iSort]
    # endif garand

    return outFiles
  # end findProfiles()

  def readASCII(self, inFile, shortWave=False):
    """
    Read a single RRTMG ASCII flux file and return the model output 
    in a dictionary to be used in makeNC()

    Input
      inFile -- string, full path to RRTMG ASCII flux file for a 
        single profile

    Output
      outDict -- dictionary with the following fields:
        level_pressure: pressure at layer boundaries (nLevel array)
        up_flux: upwelling flux (W/m2) as a function of wavenumber 
          and level (nLevel x nWavenumber array)
        net_flux: net flux (W/m2) as a function of wavenumber and
          level (nLevel x nWavenumber array)
        heat_rate: heating rate (K/day) as a function of wavenumber 
          and level (nLevel x nWavenumber array)
        wavenumber: spectral points (cm-1) vector (2 x nWavenumber)
          ([starting wavenumber of band, ending wavenumber of band])

        Longwave and Shortwave:
          down_flux: total downwelling flux (W/m2) as a function of 
            wavenumber and level (nLevel x nWavenumber array)

        Shortwave only:
          difdown_flux: diffuse down flux (W/m2) as a function of 
            wavenumber and level (nLevel x nWavenumber array)
          dirdown_flux: direct down flux (W/m2) as a function of 
            wavenumber and level (nLevel x nWavenumber array)

        NOTE: each flux field also has an associated broadband key 
          that contains an nLevel-element array of fluxes integrated 
          over the entire spectral domain

    Keywords
      shortWave -- boolean, process SW flux files instead of LW
    """

    profDat = open(inFile).read().splitlines()

    # these lists will include all spectral points and the broadband
    # pressure should be the same regardless of band
    pLev, wn1, wn2, upTot, downTot, net, hr, downDir, downDif = \
      ([] for i in range(9))

    # these lists are for single bands
    upTotBand, downTotBand, netBand, hrBand, dirBand, difBand = \
      ([] for i in range(6))
    pLevBand = []

    for line in profDat:
      split = line.split()

      if len(split) == 0:
        # empty lines imply the end of one band and the start of 
        # another, so we need to save the lists of fluxes (and HR) 
        # from the previous band and reset them for the new one
        if len(upTotBand) != 0:
          upTot.append(upTotBand)
          downTot.append(downTotBand)
          net.append(netBand)
          hr.append(hrBand)
          downDir.append(dirBand)
          downDif.append(difBand)

          # pLev can just be overwritten every band -- 
          # they are constant
          pLev = list(pLevBand)
        # end len check

        upTotBand, downTotBand, netBand, hrBand, dirBand, difBand = \
          ([] for i in range(6))

        # pLev can just be overwritten every band -- they are constant
        pLevBand = []

      elif split[0] == 'mb':
        # can skip this header info
        continue
      elif split[0] == 'LEVEL':
        # can skip this header info
        continue
      elif split[0] == 'Wavenumbers:':
        # extract spectral range of band then move to next line
        wn1.append(float(split[1]))
        wn2.append(float(split[3]))
        continue
      elif split[0] == 'Modules':
        # this is the footer, and we do not need anything from it
        break
      else:
        split = [float(i) for i in split]
        pLevBand.append(split[1])
        if len(split) == 6:
          # LW output
          upTotBand.append(split[2])
          downTotBand.append(split[3])
          netBand.append(split[4])
          hrBand.append(split[5])
        elif len(split) == 8:
          # SW output
          upTotBand.append(split[2])
          difBand.append(split[3])
          dirBand.append(split[4])
          downTotBand.append(split[5])
          netBand.append(split[6])
          hrBand.append(split[7])
        # end LW/SW

      # endif wn construction

    # end inDat loop

    outDict = {}

    outDict['wavenumber'] = np.array([wn1, wn2])[:, 1:].T

    # mbar to Pa conversion
    outDict['level_pressures'] = np.array(pLev)[::-1] * 100

    # transpose the output arrays to follow RRTMGP netCDF convention
    # and slice to separate broadband from band arrays
    outDict['up_flux'] = np.array(upTot)[1:, ::-1].T
    outDict['up_flux_BB'] = np.array(upTot)[0].T[::-1]
    outDict['net_flux'] = np.array(net)[1:, ::-1].T
    outDict['net_flux_BB'] = np.array(net)[0].T[::-1]
    outDict['heat_rate'] = np.array(hr)[1:, ::-1].T[:-1]
    outDict['heat_rate_BB'] = np.array(hr)[0].T[::-1][:-1]
    outDict['down_flux'] = np.array(downTot)[1:, ::-1].T
    outDict['down_flux_BB'] = np.array(downTot)[0].T[::-1]

    if shortWave:
      outDict['difdown_flux'] = np.array(downDif)[1:, ::-1].T
      outDict['difdown_flux_BB'] = np.array(downDif)[0].T[::-1]
      outDict['dirdown_flux'] = np.array(downDir)[1:, ::-1].T
      outDict['dirdown_flux_BB'] = np.array(downDir)[0].T[::-1]
    # end SW

    # spectrally sort the band data (not broadband) and 
    # flip the net flux definition from up-down to down-up 
    # (RRTMGP convention)
    iSort = np.argsort(outDict['wavenumber'][:, 0])
    for key in outDict.keys():
      if 'net' in key: outDict[key] *= -1

      if 'BB' in key: continue
      if key in ['wavenumber', 'level_pressures']: continue
      outDict[key] = outDict[key][:, iSort]
    # end key loop

    outDict['wavenumber'] = outDict['wavenumber'][iSort, :]

    return outDict
  # end readASCII()

  def combineProfiles(self):
    """
    Merge together the fluxes and heating rates from all profiles 
    into a single nLevel x nProfile x nBand array for each parameter
    """

    fluxDict = self.fluxes

    pLev = []
    upTot, downTot, net, hr, downDir, downDif = \
      ([] for i in range(6))
    upTotBB, downTotBB, netBB, hrBB, downDirBB, downDifBB = \
      ([] for i in range(6))

    # loop over profiles
    for iKey, key in enumerate(sorted(fluxDict.keys())):
      pLev.append(fluxDict[key]['level_pressures'])

      if self.profiles == 'garand':
        # by-band fluxes (LW and SW)
        upTot.append(fluxDict[key]['up_flux'])
        downTot.append(fluxDict[key]['down_flux'])
        net.append(fluxDict[key]['net_flux'])
        hr.append(fluxDict[key]['heat_rate'])

        # broadband (LW and SW)
        upTotBB.append(fluxDict[key]['up_flux_BB'])
        downTotBB.append(fluxDict[key]['down_flux_BB'])
        netBB.append(fluxDict[key]['net_flux_BB'])
        hrBB.append(fluxDict[key]['heat_rate_BB'])

        # SW by-band and broadband
        if self.doSW:
          downDir.append(fluxDict[key]['dirdown_flux'])
          downDif.append(fluxDict[key]['difdown_flux'])
          downDirBB.append(fluxDict[key]['dirdown_flux_BB'])
          downDifBB.append(fluxDict[key]['difdown_flux_BB'])
        # endif SW
      elif self.profiles == 'rfmip':
        upTotBB.append(fluxDict[key]['up_flux_BB'])
        downTotBB.append(fluxDict[key]['down_flux_BB'])
      # endif self.profiles
    # end fluxDict keys loop

    # now convert to arrays and assign as attributes to object
    combined = {}
    fields = self.ncFields

    if self.profiles == 'garand':  
      combined[fields[1]] = np.array(self.waveNum)

      # for transforming arrays from (nProfiles x nLevels x nBands)
      # to (nLevels x nProfiles x nBands)
      tAxes = (1,0,2)

      combined[fields[0]] = np.transpose(np.array(hr), axes=tAxes)
      combined[fields[2]] = np.array(pLev).T
      combined[fields[3]] = \
        np.transpose(np.array(downTot), axes=tAxes)
      combined[fields[4]] = np.transpose(np.array(net), axes=tAxes)
      combined[fields[5]] = \
        np.transpose(np.array(upTot), axes=tAxes)
      combined[fields[6]] = np.array(downTotBB).T
      combined[fields[7]] = np.array(netBB).T
      combined[fields[8]] = np.array(upTotBB).T
      combined[fields[9]] = np.array(hrBB).T

      if self.doSW:
        combined[fields[10]] = np.transpose(np.array(downDif), \
          axes=tAxes)
        combined[fields[11]] = np.transpose(np.array(downDir), \
          axes=tAxes)
        combined[fields[12]] = np.array(downDifBB).T
        combined[fields[13]] = np.array(downDirBB).T
      # endif SW

      self.combined = dict(combined)
    elif self.profiles == 'rfmip':
      # apparently RFMIP is from TOA to surface
      # eventually decided to exclude RRTMG/RFMIP pressure levels
      # because of the rounding done in RRTMG
      combined[fields[0]] = np.array(upTotBB)[:, ::-1] if \
        self.upwelling else np.array(downTotBB)[:, ::-1]

      if iFD == 1:
        self.combinedSW = dict(combined)
      else:
        self.combinedLW = dict(combined)
      # endif SW/LW
    # endif self.profiles

    return self
  # end combineProfiles()

  def combineRFMIP(self, inList):
    """
    Combine the flux arrays for all RFMIP experiments (each of which 
    should have had a separate rrtmg object generated) into a single 

    inList -- list of rrtmg objects (one for each RFMIP experiment)
    """

    lwExp, swExp = [], []
    for inObj in inList: 
      lwExp.append(inObj.combinedLW[self.ncFieldsLW[0]])
      swExp.append(inObj.combinedSW[self.ncFieldsSW[0]])
    # end inObj loop

    # repopulate (or populate for the first time) rrtmg object 
    # attributes
    self.nExperiments = len(lwExp)
    self.combinedLW[self.ncFieldsLW[0]] = np.array(lwExp)
    self.combinedSW[self.ncFieldsSW[0]] = np.array(swExp)
    return self
  # end combineRFMIP()

  def writeNC(self):
    """
    Write a netCDF with the data in an rrtmg object. This is done for
    each spectral domain (lw and sw)
    """

    # first copy over the netCDF templates
    cmd = [self.ncCopy, self.ncTemp, self.ncOut]
    sub.call(cmd)

    # now edit the copies with profile data
    ncObj = nc.Dataset(self.ncOut, 'r+')
    for ncVar in self.ncFields:
      ncObj.variables[ncVar][:] = self.combined[ncVar]
    # end fields loop
    ncObj.close()
  # end writeNC()

  def __init__(self, inDir, doSW=False, searchStr='OUTPUT_RRTM', \
    profiles='garand', ncTemplate=REFNCLW, \
    suffix='inputs-outputs.nc', ncCopyPath='nccopy', upwelling=False):
    """
    Extract the RRTMG flux files for a given spectral domain

    Read a single RRTMG ASCII flux file and return the model output 
    in a dictionary to be used in makeNC()

    Input
      inDir -- string, directory with RRTMG files

    Keywords
      doSW -- boolean, specifies whether SW or LW (default) is done
      searchStr -- string used for finding RRTMG ASCII files
      profiles -- string that dictates what netCDF format is used 
        (e.g., Garand, RFMIP, etc.)
      ncTemplate -- string, full path to netCDF file for the 
        specified profiles
      suffix -- string, that is appended to "rrtmg-lw" and "rrtmg-sw" 
        in the output netCDF files
      ncCopyPath -- string, full path to nccopy executable (or just 
        "nccopy" if it is in $PATH)
      upwelling -- boolean; process upwelling fluxes in the SW and LW
        (this is ONLY needed for RFMIP profiles)
    """

    self.inDir = inDir
    self.search = searchStr
    self.profiles = profiles
    self.txtFiles = self.findProfiles()
    self.ncTemp = ncTemplate
    self.ncCopy = ncCopyPath
    self.upwelling = upwelling
    self.doSW = doSW

    # determine which netCDF fields to modify
    if profiles == 'garand':
      if doSW:
        self.ncFields = NCFIELDSG + NCSWFIELDSG
      else:
        self.ncFields = list(NCFIELDSG)
      # endif doSW
    elif profiles == 'rfmip':
      # upwelling AND downwelling will be used with Garand, but we 
      # have to specify which one to do for RFMIP
      # eventually decided to exclude RRTMG/RFMIP pressure levels
      # because of the rounding done in RRTMG
      """
      self.ncFieldsLW = ['rlu', 'plev'] if upwelling else \
        ['rld', 'plev']
      self.ncFieldsSW = ['rsu', 'plev'] if upwelling else \
        ['rsd', 'plev']
      """
      self.ncFieldsLW = ['rlu'] if upwelling else ['rld']
      self.ncFieldsSW = ['rsu'] if upwelling else ['rsd']
    # endif profiles

    # read the ASCII files and store each in comprehensive dict
    profDict = {}
    for iProf, prof in enumerate(self.txtFiles):
      profDict['profile%03d' % (iProf+1)] = \
        self.readASCII(prof, shortWave=doSW)

    self.fluxes = dict(profDict)

    # we now assume that all profiles have the same number of levels
    # and that the number is the same for each both spectral domains
    self.nLevels = profDict['profile001']['level_pressures'].shape[0]
    self.nLayers = self.nLevels - 1

    self.waveNum = profDict['profile001']['wavenumber']
    self.nBands = profDict['profile001']['wavenumber'].shape[0]

    # now merge the profiles
    self.combineProfiles()

    # output filename construction
    domainStr = 'sw' if doSW else 'lw'
    self.ncOut = 'rrtmg-%s-%s' % (domainStr, suffix)

  # end constructor
# end rrtmg()

if __name__ == '__main__':
  parser = argparse.ArgumentParser(\
    description='Convert ASCII RRTMG output to netCDF format.  ' + \
    'A netCDF for both the LW and SW is written to working directory.')
  parser.add_argument('--mode', type=str, default='garand', \
    help='String that directs the script on what netCDF format ' + \
      'to use [garand, rfmip].')
  parser.add_argument('--lw_dir', type=str, \
    default='%s/LW/runs_42prof_clr' % TOPDIR, \
    help='Directory with RRTGM LW results.')
  parser.add_argument('--sw_dir', type=str, \
    default='%s/SW/runs_42prof_clr/sza_0_alb_0.2/' % TOPDIR, \
    help='Directory with RRTGM SW results.')
  parser.add_argument('--search', type=str, default='OUTPUT_RRTM', \
    help='Search string that will be used to find RRTMG output ' + \
    'ASCII files.')
  parser.add_argument('--suffix', type=str, \
    default='inputs-outputs.nc', \
    help='Output netCDF filename suffix appended to "rrtmg-?w-" ' + \
    '(so for the default "inputs-outputs.nc" and for the LW, the ' + \
    'output netCDF filename would be "rrtmg-lw-inputs-outputs.nc.")')
  parser.add_argument('--lw_template', type=str, default=REFNCLW, \
    help='Full path to netCDF that will be used as a template ' + \
    'on which the output LW netCDF will be based.')
  parser.add_argument('--sw_template', type=str, default=REFNCSW, \
    help='Full path to netCDF that will be used as a template ' + \
    'on which the output SW netCDF will be based.')
  parser.add_argument('-n', '--nccopy_path', type=str, \
    default='/nas/project/p1770/dependencies/bin/nccopy', \
    help='Full path to the nccopy executable in the C netCDF ' + \
    'library (must be version 4.3.0 or newer).')
  parser.add_argument('--upwelling', action='store_true', \
    help='For RFMIP only -- process upwelling fluxes and not ' + \
    'downwelling.')
  args = parser.parse_args()

  lwDir = args.lw_dir; utils.file_check(lwDir)
  swDir = args.sw_dir; utils.file_check(swDir)

  ncMode = args.mode.lower()
  if ncMode not in MODES: sys.exit('Set mode to any of %s' % MODES)

  ncTempLW = args.lw_template; utils.file_check(ncTempLW)
  ncTempSW = args.sw_template; utils.file_check(ncTempSW)
  ncCopy = args.nccopy_path; utils.file_check(ncCopy)

  if ncMode == 'garand':
    # LW
#    rrtmgObj = rrtmg(lwDir, searchStr=args.search, profiles=ncMode, \
#      ncTemplate=ncTempLW, suffix=args.suffix, ncCopyPath=ncCopy)
#    rrtmgObj.writeNC()
#    print('LW done')

    # SW
    rrtmgObj = rrtmg(swDir, searchStr=args.search, profiles=ncMode, \
      ncTemplate=ncTempSW, suffix=args.suffix, ncCopyPath=ncCopy, \
      doSW=True)
    rrtmgObj.writeNC()
    print('SW done')
  elif ncMode == 'rfmip':
    sys.exit('RFMIP code has to be separated into LW and SW.')
    # generate a separate rrtmg object for each RFMIP experiment
    rfmipObj = []
    for iProf in range(1, 19):
      lwDirEx = '%s/RFMIP_experiment_%02d' % (lwDir, iProf)
      swDirEx = '%s/RFMIP_experiment_%02d' % (swDir, iProf)
      utils.file_check(lwDirEx); utils.file_check(swDirEx)
      print('Working on RFMIP Experiment %d' % iProf)

      rrtmgObj = rrtmg(lwDirEx, swDirEx, searchStr=args.search, \
        profiles=ncMode, templateLW=ncTempLW, templateSW=ncTempSW, \
        suffix=args.suffix, ncCopyPath=ncCopy, \
        upwelling=args.upwelling)
      rfmipObj.append(rrtmgObj)
    # end profile loop

    # combine fluxes for all expereiments and then write the 
    # RFMIP netCDF files
    rrtmgObj.combineRFMIP(rfmipObj)
    rrtmgObj.writeNC()

  # endif ncMode
# end main()

