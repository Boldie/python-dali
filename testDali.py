#!/usr/bin/python
from __future__ import print_function

import argparse
import logging
 
log_format = '%(levelname)s: %(message)s'
logging.basicConfig(format=log_format, level=logging.DEBUG)

parser = argparse.ArgumentParser(description='A dali helper script usable for a DALI-USB interface.')

subparsers = parser.add_subparsers(dest="command",title="commands", metavar="COMMAND")
cmd_interactive = subparsers.add_parser("interactive", help="Interactive console usage of this script for testing and actions.")
cmd_find = subparsers.add_parser("find", help="Tries to find ballasts and assign short addresses to them if they have none.")
cmd_resetAndFind = subparsers.add_parser("resetAndFind", help="Tries to find ballasts and assign a short-address to them.")
cmd_query = subparsers.add_parser("query", help="Query all short addresses and records the set group and scene details.")
cmd_apply = subparsers.add_parser("apply", help="Apply a settings file to the devices.")
cmd_apply.add_argument('filename', type=str, help='filename to load data from')
cmd_apply.add_argument('--with-device-config', dest="withDeviceConfig", action="store_true", default=False, help='Writes device settings')

args = parser.parse_args()
from dali.driver import hasseb
d=hasseb.HassebUsb()
d._openDevice()
from dali.address import *
from dali.gear.general import *

from dali.gear.general import QueryDeviceType

import json
logger = logging.getLogger(__name__)

class DaliDevicesState():
    """
    This class can be used to query and restore states / information for different
    modules to the DALI bus or read it from the DALI bus and store / load things
    from a JSON file.
    """
    def __init__(self):
        self._initData()
        
    def _initData(self):
        self.data = { "devices": {}, "groups": {}, "scenes": {} }
    
    def readFromJson(self, filename):
        with open(filename) as data_file:    
            data = json.load(data_file)
         
        #####################################################   
        # Convert some stuff to better interpretable later
        
        # Ensure keys of groups are of type int
        data["groups"] = {int(k): v for k, v in data["groups"].items()}
        data["devices"] = {int(k): v for k, v in data["devices"].items()}
        data["scenes"] = {int(k): v for k, v in data["scenes"].items()}
        
        newScenesData = {} 
        for sceneId, sceneData in data["scenes"].iteritems():
            singleScene = {}
            for key, value in sceneData.iteritems():
                for splitKey in key.split(","):
                    if splitKey != "default":
                        splitKey = int(splitKey)
                    singleScene[splitKey] = value;
            newScenesData[sceneId] = singleScene
        data["scenes"] = newScenesData   
        self.data = data
        
    def writeToJson(self, filename):
        with open(filename, 'w') as outfile:
            json.dump(self.data, outfile)
            
    def writeGroupsToDali(self, dali):        
        logger.info("Writing group stuff to DALI-device")
        
        # Remark: Non named groups from file will be left untouched nor will be
        # deleted from devices.
        for deviceShortAddr in self.data["devices"].keys():
            logging.debug("Device %u: Query for groupmask"%(deviceShortAddr))
            # Get group info may speedup setting things later on.
            grp = d.send(QueryGroupsZeroToSeven(deviceShortAddr))
            grp2 = d.send(QueryGroupsEightToFifteen(deviceShortAddr))
            groupMask = grp2.value.as_integer << 8 | grp.value.as_integer
            logging.debug("Device %u: Groupmask: 0x%x"%(deviceShortAddr,groupMask))
            
            for groupId in range(16):
                currentlyMemberOfGroup = (groupMask & (1<<groupId)) != 0
                memberOfGroup=groupId in self.data["groups"] and deviceShortAddr in self.data["groups"][groupId]                
                # logging.debug("Device %u / group %u: member: %r, newMember: %r"%(deviceShortAddr,groupId,currentlyMemberOfGroup,memberOfGroup))
                if memberOfGroup != currentlyMemberOfGroup:
                    logging.debug("Device %u: Correcting group (%u) assignment"%(deviceShortAddr,groupId))
                    if memberOfGroup:
                        dali.send( AddToGroup( Short(deviceShortAddr), groupId ))
                    else:
                        dali.send( RemoveFromGroup( Short(deviceShortAddr), groupId ))
        logger.info("Writing group stuff to DALI-device was successful")
                        
    def writeScenesToDali(self, dali):
        for (sceneId, sceneContent) in self.data["scenes"].iteritems():
            logging.debug("Working on Scene %u"%(sceneId))      
            for deviceShortAddr in self.data["devices"].keys():
                sceneValue = None                
                if deviceShortAddr in sceneContent:
                    sceneValue = sceneContent[deviceShortAddr]
                elif "default" in  sceneContent:
                    sceneValue = sceneContent["default"]
                
                if sceneValue is not None:
                    logging.debug("Device %u: Set scene level to %u"%(deviceShortAddr,sceneValue))      
                    dali.send( DTR0(sceneValue) )
                    dali.send( SetScene(deviceShortAddr,sceneId) )
                    r = dali.send(QuerySceneLevel(deviceShortAddr,sceneId))
                    if r.value.as_integer != sceneValue:
                        logging.error("Device %u: Set scene level to %u FAILED (query retrieves: %u)"%(deviceShortAddr,sceneValue,r.value.as_integer))
                else:
                    logging.debug("Device %u: Remove from scene"%(deviceShortAddr))      
                    dali.send( RemoveFromScene(Short(deviceShortAddr),sceneId) )
                    
    def writeDeviceSettingsToDali(self, dali):
        logger.info("Writing device settings stuff to DALI-devices")
        for deviceShortAddr, data in self.data["devices"].iteritems():
            if "sysFailLevel" in data:
                sfl = data["sysFailLevel"]
                dali.send( DTR0(sfl) )
                dali.send(SetSystemFailureLevel(deviceShortAddr))
                r = dali.send(QuerySystemFailureLevel(deviceShortAddr))
                if r.value.as_integer != sfl:
                    logging.error("Device %u: Set system failure level to %u FAILED (query retrieves: %u)"%(deviceShortAddr,sfl,r.value.as_integer))
            if "powerOnLevel" in data:
                pol = data["powerOnLevel"]
                dali.send( DTR0(pol) )
                dali.send(SetPowerOnLevel(deviceShortAddr))
                r = dali.send(QueryPowerOnLevel(deviceShortAddr))
                if r.value.as_integer != pol:
                    logging.error("Device %u: Set power on level to %u FAILED (query retrieves: %u)"%(deviceShortAddr,pol,r.value.as_integer))
                
                
            
    def writeToDali(self, dali):
        self.writeGroupsToDali( dali )
        self.writeScenesToDali( dali )
        
if args.command == "interactive":
    try:
        import rlcompleter  
        import readline
        readline.parse_and_bind("tab: complete")
    except ImportError:
        pass
    
    import code
    print(" Entering interactive mode. For e.g. to send the Value 99 to Dail bus use")
    print(" > d.send(DAPC(Short(0), 99))")    
    code.interact(local=locals())
if args.command == "apply":
    ds = DaliDevicesState()
    ds.readFromJson(args.filename)
    
    if args.withDeviceConfig:
        ds.writeDeviceSettingsToDali(d)
    
    ds.writeToDali(d)
if args.command == "query":
    from dali.address import Short
    from dali.gear.general import EnableDeviceType
    from dali.gear.general import QueryDeviceType
    from dali.gear.emergency import QueryEmergencyFailureStatus
    from dali.gear.emergency import QueryEmergencyFeatures
    from dali.gear.emergency import QueryEmergencyMode
    from dali.gear.emergency import QueryEmergencyStatus
    from dali.interface import DaliServer

     
    for addr in range(0, 64):
        cmd = QueryDeviceType(Short(addr))
        r = d.send(cmd)
     
        if r.value is not None:
            logging.info("[%d]: resp: %s" % (addr, unicode(r)))
            
            # Query group info
            grp = d.send(QueryGroupsZeroToSeven(addr))
            grp2 = d.send(QueryGroupsEightToFifteen(addr))
            
            #import code
            #code.interact(local=locals())
            logging.info("   Grp 0-7 : 0x%x"%(grp.value.as_integer))
            logging.info("   Grp 8-15: 0x%x"%(grp2.value.as_integer))
            
            
    
            if r.value == 1:
                d.send(EnableDeviceType(1))
                r = d.send(QueryEmergencyMode(Short(addr)))
                logging.info(" -- {0}".format(r))
         
                d.send(EnableDeviceType(1))
                r = d.send(QueryEmergencyFeatures(Short(addr)))
                logging.info(" -- {0}".format(r))
         
                d.send(EnableDeviceType(1))
                r = d.send(QueryEmergencyFailureStatus(Short(addr)))
                logging.info(" -- {0}".format(r))
         
                d.send(EnableDeviceType(1))
                r = d.send(QueryEmergencyStatus(Short(addr)))
                logging.info(" -- {0}".format(r))
              
    raise SystemExit(0)      
elif args.command == "find" or args.command == 'resetAndFind':
    from dali.gear.general import Compare
    from dali.gear.general import Initialise
    from dali.gear.general import Randomise
    from dali.gear.general import SetSearchAddrH
    from dali.gear.general import SetSearchAddrL
    from dali.gear.general import SetSearchAddrM
    from dali.gear.general import Terminate
    from dali.gear.general import Withdraw
    import sys
    import time
 
    
    class BallastFinder():
        """
        The finder is used to assign addresses to the ballasts. This can be made in
        random order or in the so called interactive mode which allows the operator
        to set a specific address to a device. If one ballast was found, it will 
        flash on and off so it can be identified. The operator is then asked for a
        number.
        """
        
        def __init__(self, ifc, interactive=False, assignOnlyUnassigned=False):
            """
            Initializes the class with the interface ifc used for communication and
            set interactive to the desired mode. For description of interactive mode
            see class description
            """
            self.ifc = ifc
            self.nextShortAddress = 63
            
            self.interactive = interactive
            self.assignOnlyUnassigned = assignOnlyUnassigned
            self.assignedAddresses = []
            
            self._switchToFullAssign()
            
        def _switchToFullAssign(self):
            self.resetShortAddresses = True
            self.randomize = True
            self.onBallastFound = self._assignAddress;
            
        def _switchToAssignUnassigned(self):
            self.resetShortAddresses = False
            self.randomize = False
            self.onBallastFound = self._assignAddress;
            
        def _switchToQueryShortAdresses(self):
            self.resetShortAddresses = False
            self.randomize = True
            self.onBallastFound = self._queryExistingShortAddress;
            
        def set_search_addr(self, addr):
            self.ifc.send(SetSearchAddrH((addr >> 16) & 0xff))
            self.ifc.send(SetSearchAddrM((addr >> 8) & 0xff))
            self.ifc.send(SetSearchAddrL(addr & 0xff))
            
        def enter_interactive_mode(self):
            # First program a free short address and remember it
            if self.nextShortAddress in self.assignedAddresses:
                for i in xrange(63,-1,-1):
                    if i not in self.assignedAddresses:
                        self.nextShortAddress = i
                        break 
                                                  
            self.ifc.send(ProgramShortAddress(self.nextShortAddress))
            
            while True:
                print("Enter number to assign to flashing ballast or press enter to flash again: ")
                # Flash the ballast
                time.sleep(1)
                self.ifc.send(DAPC(Short(self.nextShortAddress), 0))
                time.sleep(1)
                self.ifc.send(DAPC(Short(self.nextShortAddress), 254))
                
                try:
                    newAddress = int(raw_input())
                except:
                    continue
    
                if newAddress < 0 or newAddress >=64:
                    print("ERROR: Out of range")
                    continue
                if newAddress in self.assignedAddresses:
                    print("ERROR: Address already chosen")
                    continue;
            
                self.ifc.send(ProgramShortAddress(newAddress))
            
                # It seems to be quite enough to set the address again.
                #self.ifc.send(DTR0(newAddress<<1 | 0x01))
                #self.ifc.send(SetShortAddress(Short(self.nextShortAddress) ))
                self.assignedAddresses.append(newAddress)
                return newAddress
        
        def find_next(self, low, high):
            """Find the ballast with the lowest random address.  The caller
            guarantees that there are no ballasts with an address lower than
            'low'.
            """
            logging.info("Searching from {} to {}...".format(low, high))
            if low == high:
                self.set_search_addr(low)
                response = self.ifc.send(Compare())
        
                if response.value is True:
                    self.onBallastFound(low)                        
                    self.ifc.send(Withdraw())                        
                    return low
                return None
        
            self.set_search_addr(high)
            response = self.ifc.send(Compare())
        
            if response.value is True:
                midpoint = (low + high) / 2
                return self.find_next(low, midpoint) or self.find_next(midpoint + 1, high)
        
        def _assignAddress(self, address):
            """ This is the classical assignment method on match.
            """
            if self.interactive:
                logging.info("Found ballast at {} starting identification ...".format(address))                    
                self.ifc.send(ProgramShortAddress(self.nextShortAddress))
                newAddress = self.enter_interactive_mode()
                logging.info("Found ballast at {}; assigning short-address {} and withdrawing it...".format(address, newAddress))
            else:
                logging.info("Found ballast at {}; assigning short-address {} and withdrawing it...".format(address, self.nextShortAddress))
                self.ifc.send(ProgramShortAddress(self.nextShortAddress))
                self.nextShortAddress += 1  

        def _queryExistingShortAddress(self, longAddress):
            rv = self.ifc.send(QueryShortAddress())
            shortAddress = rv._value.as_integer >> 1
            logging.info("Found ballast at long={} with shortAddress={}".format(hex(longAddress), shortAddress))
            if shortAddress < 64:
                self.assignedAddresses.append(shortAddress)
            
        def find_ballasts(self, broadcast):
            _ballasts = []
        
            # Reset all short addresses to get rid of problems while temporary assignment
            if self.resetShortAddresses:
                self.ifc.send(DTR0(0xff))
                self.ifc.send(SetShortAddress(Broadcast()))
            
            self.ifc.send(Terminate())
            self.ifc.send(Initialise(broadcast=broadcast, address=None))
            
            if self.randomize:
                self.ifc.send(Randomise())
                time.sleep(0.1)  # Randomise may take up to 100ms
        
            low = 0
            high = 0xffffff
            while low is not None:
                low = self.find_next(low, high)
                if low is not None:
                    _ballasts.append(low)
                    low += 1
        
            self.ifc.send(Terminate())
            return _ballasts
        
        def run(self):
            if self.assignOnlyUnassigned:
                self._switchToQueryShortAdresses()
                self.find_ballasts(broadcast=True)
                self._switchToAssignUnassigned()
                return self.find_ballasts(broadcast=False)
            else:
                self._switchToFullAssign()
                return self.find_ballasts(broadcast=True)
    
    finder = BallastFinder(d, interactive=True, assignOnlyUnassigned=args.command!='resetAndFind')
    ballasts = finder.run()
    print("{} ballasts found:".format(len(ballasts)))
    print(ballasts)
