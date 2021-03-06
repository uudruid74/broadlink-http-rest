#!/usr/bin/python3
#- Note python 3.6 or later now required!
import os
from importlib import reload
import settings
import traceback
import datetime
import devices
import threading
import threadpool
import configparser
import sys
import getopt
import time
import netaddr
import signal
import socket
import errno
import json
import macros
import re
import collections
import platform
import pdb
import socketserver
import mimetypes
import http.server
from devices import logfile
from plugins import *

def reloadAll():
    reload(devices)
    reload(plugins)
#    reload(device_broadlink)
#    reload(device_url)
#    reload(device_gpio)
#    reload(device_scheduler)
#    reload(device_log)
#    reload(device_virtual)
    reload(settings)

class Handler(http.server.BaseHTTPRequestHandler):
    # Parameters = collections.defaultdict(lambda : ' ')
    def _set_headers(self,path):
        if path == '/':
            self.send_response(301)
            self.send_header('Location','/ui/index.html')
            self.end_headers()
            return
        self.send_response(200)
        filetype = 'application/json'
        if path.find('?') != -1:
            shortpath = path[:path.find('?')]
        else:
            shortpath = path
        (guesstype,encoding) = mimetypes.guess_type(shortpath,False)
        if guesstype is not None:
            filetype = guesstype
        if encoding is not None:
            self.send_header('Content-Encoding', encoding)
        self.send_header('Content-Type', filetype)
        self.send_header('Access-Control-Allow-Origin','*')
        #- Cache icons and UI library code for min 90 days, images for 30 days
        #- Normal UI html and css files are cached for at least 7 days
        if 'getIcon' in path or '/ui/lib/' in path:
            self.send_header('Cache-Control', 'max-age=7776000'); #- 90 days
        elif '/ui/images/' in path:
            self.send_header('Cache-Control', 'max-age=2592000'); #- 30 days
        elif '/ui/' in path:
            self.send_header('Cache-Control', 'max-age=604800');  #-  7 days
        self.end_headers()

    def client_ip(self):
        if hasattr(self,"headers"):
            remote_ip = self.headers.get('X-Forwarded-For', self.headers.get('X-Real-Ip', self.client_address[0]))
        else:
            remote_ip = self.client_address[0]
        return remote_ip

    def log_message(self, format, *args):
        logfile("%s/%s - - [%s] %s" %
            (str(self.server.threadid).rjust(2),self.client_ip(),self.log_date_time_string(),format%args),"INFO")

    def do_OPTIONS(self):
        self.send_response(200, "ok")
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        self.Parameters = collections.defaultdict(lambda : ' ')
        try:
            if GlobalPassword and ('/ui/' not in self.path and 'getIcon' not in self.path and self.path != '/favicon.ico'):
                try:
                    if RestrictAccess and self.client_ip() not in RestrictAccess:
                        return self.access_denied()
                    return self.messageHandler()
                except NameError as e:
                    logfile ("Error: %s" % e,"ERROR")
                    traceback.print_exc()
                    self.password_required()
            else:
                return self.messageHandler()
        except NameError:                   #- No security specified
            self.messageHandler()

    def do_POST(self):
        self.Parameters = collections.defaultdict(lambda : ' ')
        password = ''
        try:
            content_len = int(self.headers.get('content-length', 0))
            JSONbody = self.rfile.read(content_len).decode("utf-8")
            #print ("POST body: %s" % JSONbody)
            self.Parameters.update(json.loads(JSONbody))
            password = self.Parameters['password'];
        except:
            traceback.print_exc()
            pass
        try:
            if not GlobalPassword:
                return self.messageHandler()
            if GlobalPassword and GlobalPassword == password:
                return self.messageHandler()
            else:
                logfile ('''POST Password Wrong: "%s"''' % password,"WARN")
        except NameError:
                return self.password_required()
        self.password_required()

    def password_required(self):
        response = "POST Password required from %s" % self.client_ip()
        self._set_headers(self.path)
        self.wfile.write(bytes('''{ "error": "%s" }''' % response,'utf-8'))
        logfile (response,"WARN")
        #self.close_connection = True
        return False

    def access_denied(self):
        response = "Client %s is not allowed to use GET!" % self.client_ip()
        self._set_headers(self.path)
        self.wfile.write(bytes('''{ "error": "%s" }''' % response,'utf-8'))
        logfile (response,"WARN")
        #self.close_connection = True
        return False

    def messageHandler(self):
        if 'favicon' in self.path:
            return False

        if '..' in self.path:
            return False

        self._set_headers(self.path)
        if '?' in self.path:
            (self.path,query) = self.path.split('?')
            params = re.split('[&=]+',query)
            for index in range(0,len(params),2):
                self.Parameters[params[index]] = params[index+1]
        paths = re.split('[//=]+',self.path)

        if 'learnCommand' in self.path:
            try:
                if self.client_ip() not in LearnFrom:
                    logfile ("Won't learn commands from %s.  Access Denied!" % self.client_ip(),"WARN",attrs=['bold'])
                    return False
            except NameError:
                pass

            if paths[2] == 'learnCommand':
                deviceName = paths[1]
                commandName = paths[3]
            else:
                commandName = paths[2]
                deviceName = devices.Dev['default']
            self.Parameters["device"] = deviceName
            result = learnCommand(commandName,self.Parameters)
            if result == False:
                response = "Failed: No command learned"
            else:
                response = "Learned: %s" % commandName

        elif 'sendCommand' in self.path:
            if paths[2] == 'sendCommand':
                deviceName = paths[1]
                commandName = paths[3]
            else:
                commandName = paths[2]
                deviceName = devices.Dev['default']
            self.Parameters["device"] = deviceName
            result = sendCommand(commandName, self.Parameters)
            if result == False:
                response = "Failed: Unknown command - %s" % commandName
            elif result == True:
                response = commandName
            else:
                response = result

        elif 'getType' in self.path:
            if paths[2] == 'getType':
                varName = paths[3]
                deviceName = paths[1]
            else:
                varName = paths[2]
                deviceName = devices.Dev['default']
            self.Parameters["device"] = deviceName
            (status,varlist) = getType(varName,self.Parameters)
            if (status):
                if varlist is None:
                    response = '''{ "%s": "%s" }''' % (varName,status)
                else:
                    response = '''{\n\t"%s": "%s",\n\t"device": "%s",\n\t"%s": "%s"\n}''' % (varName,status,deviceName,status,varlist)
            else:
                response = "Failed: Unknown command - %s" % varName

        elif 'getStatus' in self.path:
            if paths[2] == 'getStatus':
                commandName = paths[3]
                deviceName = paths[1]
            else:
                commandName = paths[2]
                deviceName = devices.Dev['default']
            self.Parameters["device"] = deviceName
            status = getStatus(commandName,self.Parameters)
            if (status):
                response = '''{ "%s": "%s" }''' % (commandName,status)
            else:
                response = "Failed: Unknown command - %s" % commandName

        elif 'setStatus' in self.path:
            if paths[2] == 'setStatus':
                commandName = paths[3]
                deviceName = paths[1]
                status = paths[4]
            else:
                commandName = paths[2]
                deviceName = devices.Dev['default']
                status = paths[3]
            self.Parameters["device"] = deviceName
            result = setStatus(commandName, status, self.Parameters)
            if (result):
                response = '''{ "%s": "%s" }''' % (commandName, result)
            else:
                response = "Failed: Unknown command - %s" % commandName

        elif 'toggleStatus' in self.path:
            if paths[2] == 'toggleStatus':
                commandName = paths[3]
                deviceName = paths[1]
            else:
                commandName = paths[2]
                deviceName = devices.Dev['default']
            self.Parameters["device"] = deviceName
            status = toggleStatus(commandName, self.Parameters)
            if (status):
                response = '''{ "%s": "%s" }''' % (commandName, status)
            else:
                response = "Failed: Unknown command - %s" % commandName

        #- Should UI based commands really be local only?
        elif 'listEvents' in self.path:
#            if RestrictAccess and self.client_ip() not in RestrictAccess:
#                return self.access_denied()
            response = macros.eventList.dump()

        elif 'listDevices' in self.path:
#            if RestrictAccess and self.client_ip() not in RestrictAccess:
#                return self.access_denied()
            response = devices.dumpDevices()

        elif 'listRooms' in self.path:
#            if RestrictAccess and self.client_ip() not in RestrictAccess:
#                return self.access_denied()
            response = devices.dumpRooms()

        elif 'getIcon' in self.path:
#            if RestrictAccess and self.client_ip() not in RestrictAccess:
#                return self.access_denied()
            devname,exten = os.path.splitext(paths[len(paths)-1])
            pathname = "ui/" + settings.DefaultUI + '/icons/'
            socket = self.connection
            for icon in devices.Dev[devname]['Icons'].split():
                filename = pathname+icon+exten
                if os.path.isfile(filename):
                    break
            try:
                with open(filename,'rb') as f:
                    socket.sendfile(f,0)
                logfile("\t%s\n" % filename,"LOG")
            except Exception as e:
                logfile("\t%s - %s\n" % (filename,e),"WARN")
            return

        elif 'getCustomDash' in self.path:
#            if RestrictAccess and self.client_ip() not in RestrictAccess:
#                return self.access_denied()
            retval = devices.getDash()
            if (retval is not False):
                retval = macros.expandVariables(retval,self.Parameters)
                response = '''{ "ok": "%s" }''' % retval
            else:
                response = '''{ "error": "No Dash Found" }'''

        elif 'getHomeName' in self.path:
#            if RestrictAccess and self.client_ip() not in RestrictAccess:
#                return self.access_denied()
            response = '''{ "ok": "%s" }''' % devices.getHome()

        elif 'listStatus' in self.path:
#            if RestrictAccess and self.client_ip() not in RestrictAccess:
#                return self.access_denied()
            if len(paths) > 2 and paths[2] == 'listStatus':
                section = paths[1] + " Status"
            else:
                section = "Status"
            response = '''{\n\t"ok": "%s"''' % section
            if settingsFile.has_section(section):
                for var in settingsFile.options(section):
                    response += ''',\n\t"%s": "%s"''' % (var,settingsFile.get(section,var))
            response += '''\n}'''

        elif 'deleteEvent' in self.path:
            if RestrictAccess and self.client_ip() not in RestrictAccess:
                return self.access_denied()
            if paths[2] == 'deleteEvent':
                event = paths[3]
            else:
                event = paths[2]
            retval = macros.eventList.delete(event)
            if retval is not None:
                response = '''{ "ok": "%s deleted" }''' % retval.name
            else:
                response = "Failed - no such event: %s" % event

        elif '/ui/' in self.path:
            if self.path.find('?') != -1:
                shortpath = self.path[:self.path.find('?')]
            else:
                shortpath = self.path
            
#            if RestrictAccess and self.client_ip() not in RestrictAccess:
#                return self.access_denied()
            if '/ui/lib/' in shortpath:
                path = "ui/lib/" + shortpath.split('ui/lib/',1)[1]
            else:
                path = "ui/" + settings.DefaultUI + '/' + shortpath.split('/ui/',1)[1]
            socket = self.connection
            try:
                with open(path,'rb') as f:
                    socket.sendfile(f,0)
                logfile("\t%s\n" % path,"LOG")
            except Exception as e:
                logfile("\t%s - %s\n" % (path,e),"WARN")
            return

        elif self.path is '/':
            #logfile("Default Site","WARN")
            return

        elif 'getSensor' in self.path:
            if paths[2] == 'getSensor':
                sensor = paths[3]
                deviceName = paths[1]
            else:
                sensor = paths[2]
                deviceName = devices.Dev['default']
            self.Parameters["device"] = deviceName
            result = getSensor(sensor, self.Parameters)
            if result == False:
                response = "Failed to get data"
            else:
                response = '''{ "%s": "%s" }''' % (sensor, result)
        else:
            response = "Failed"
        if "Failed" in response or "error" in response[:20]:
            self.wfile.write(bytes('''{ "error": "%s" }''' % response,'utf-8'))
        elif response.startswith('{'):
            self.wfile.write(bytes(response,'utf-8'))
        else:
            self.wfile.write(bytes('''{ "ok": "%s" }''' % response,'utf-8'))
#        logfile (response+"\n","INFO")
#        print("")


def sendCommand(commandName,params):
    if commandName.startswith('.') or commandName.startswith('MACRO'):
        return macros.checkMacros(commandName,params)
    if '/' in commandName:
        (deviceName,commandName) = commandName.split('/',1)
        params = params.copy()
        params['device'] = deviceName
        if commandName == "on" or commandName == "off" or commandName == "dim" or commandName == "bright":
            commandName = (deviceName + commandName).lower()
    else:
        deviceName = params['device']
    if deviceName in devices.DeviceByName:
        device = devices.DeviceByName[deviceName]
        serviceName = deviceName + ' Commands'
    else:
        return "Failed: No such device, %s" % deviceName
    if "deviceDelay" not in params:
        params["deviceDelay"] = device.delay
    if params["deviceDelay"] == None:
        params["deviceDelay"] = 0.2
    params["command"] = commandName #- VERY IMPORTANT!

    if commandName is None or commandName is False or type(commandName) is bool:
        logfile ("Check your setting.ini for invalid syntax!!","ERROR")
        traceback.print_exc()
        return False
    if commandName.strip() != '':
        result = macros.checkConditionals(commandName,params)
        if result:
            return result
        command = newCommandName = False
        isRepeat = False
        if 'PRINT' not in commandName and 'MACRO' not in commandName and '.' not in commandName:
            if commandName.endswith("on"):
                newCommandName = commandName[:-2]
                params[commandName + ' side-effect'] = True
                if getStatus(newCommandName,params) == '1':
                    isRepeat = True
                else:
                    setStatus(newCommandName, '1', params)
            elif commandName.endswith("off"):
                newCommandName = commandName[:-3]
                params[commandName + ' side-effect'] = True
                if getStatus(newCommandName, params) == '0':
                    isRepeat = True
                else:
                    setStatus(newCommandName, '0', params)

        if settingsFile.has_option(serviceName, commandName):
            command = settingsFile.get(serviceName, commandName)
        elif settingsFile.has_option('Commands', commandName):
            command = settingsFile.get('Commands', commandName)
        if command is False and isRepeat is False:
            if settingsFile.has_option(serviceName, newCommandName):
                command = settingsFile.get(serviceName, newCommandName)
                params['command'] = newCommandName
            elif settingsFile.has_option('Commands', newCommandName):
                command = settingsFile.get('Commands', newCommandName)
                params['command'] = newCommandName
        elif command is False and isRepeat is True:
            #- If we have a defined "toggle", ignore it.
            #- Otherwise, it's not a toggle and send it through
            if settingsFile.has_option('Commands', newCommandName):
                return "fail: %s was ignored" % commandName
        if command is False:
            result = macros.checkMacros(commandName,params)
        else:
            result = macros.checkMacros(command,params)
        if result:
            return result

        with devices.Dev[deviceName]['Lock']:
            send = devices.Dev[deviceName]['sendCommand']
            if send is not None:
                result = send(command,device,deviceName,params)
        if result:
            return commandName
        return False


def getType(statusName,params):
    deviceName = params["device"]
    if deviceName in devices.DeviceByName:
        device = devices.DeviceByName[deviceName]
    else:
        logfile ("Failed: No such device, %s" % deviceName, "ERROR")
        return False

    sectionName = "RADIO " + statusName
    if settingsFile.has_section(sectionName):
        if settingsFile.has_option(sectionName,"commands"):
            varlist = settingsFile.get(sectionName,"commands")
            pattern = re.compile("\s*(commands|device|deviceDelay)\s*")
            varlist = pattern.sub ('',varlist)
            return ("list",varlist)
        else:
            varlist = settingsFile.options(sectionName);
            if "device" in varlist:
                varlist.remove("device")
            if "deviceDelay" in varlist:
                varlist.remove("deviceDelay")
            if "sequence" in varlist:
                varlist.remove("sequence")
            varlist = ' '.join(varlist)
            return ("list",varlist)
    return ("string",None)


def learnCommand(commandName, params):
    deviceName = params["device"]
    try:
        if deviceName in devices.DeviceByName:
            device = devices.DeviceByName[deviceName]
            sectionName = deviceName + ' Commands'
        else:
            logfile ("Failed: No such device, %s" % deviceName,"ERROR")
            return False
        if OverwriteProtected and settingsFile.has_option(sectionName,commandName):
            logfile ("Command %s alreadyExists and changes are protected!" % commandName,"ERROR")
            return False
    except Exception as e:
        traceback.print_exc()

    with devices.Dev[deviceName]['Lock']:
        logfile ("Waiting %d seconds to capture command" % GlobalTimeout,"SPECIAL")

        decodedCommand = devices.Dev[deviceName]['learnCommand'](deviceName,device,params)
        with devices.SettingsLock:
            settings.backupSettings()
            try:
                ControlIniFile = open(os.path.join(settings.applicationDir, 'settings.ini'), 'w')
                if not settingsFile.has_section(sectionName):
                    settingsFile.add_section(sectionName)
                settingsFile.set(sectionName, commandName, str(decodedCommand,'utf8'))
                settingsFile.write(ControlIniFile)
                ControlIniFile.close()
                return commandName
            except Exception as e:
                logfile("Error writing settings file: %s" % e,"ERROR")
                traceback.print_exc()
                settings.restoreSettings()
    return False


#- The setStatus command is not designed to perform actions, use sendCommand
#- instead with on/off appended or pass a parameter.  Use setStatus for
#- setting variables.
def setStatus(commandName, status, params):
    if '/' in commandName:
        (deviceName,commandName) = commandName.split('/')
        params = params.copy()
        params['device'] = deviceName
    else:
        deviceName = params["device"]
    if 'globalVariable' not in params or params['globalVariable'] != commandName:
        sectionName = deviceName + " Status"
    else:
        sectionName = 'Status'          #- Where the variables are stored

    #print ("setStatus command = %s status = %s devicename = %s section = %s" % (commandName, status, deviceName, sectionName))
    settings.backupSettings()
    oldvalue = getStatus(commandName,params)
    section = "TRIGGER " + commandName  #- Where trigger commands are stored
    if oldvalue == status:
        default= "%s/%s not changed: %s" % (deviceName,commandName, status)
        if settingsFile.has_option(section, "nop"):
            rawcommand = settingsFile.get(section,"nop")
        else:
            rawcommand = ".PRINT %s" % default
        macros.eventList.add("%s-NOP" % commandName,0,rawcommand,params)
        params[commandName+' side-effect'] = True
        return oldvalue
    func = devices.Dev[deviceName]["setStatus"]
    if func is not None:
        retval = func(deviceName,commandName,params,oldvalue,status)
    try:
        with devices.SettingsLock:
            if not settingsFile.has_section(sectionName):
                settingsFile.add_section(sectionName)
            ControlIniFile = open(os.path.join(settings.applicationDir, 'settings.ini'), 'w')
            settingsFile.set(sectionName, commandName, str(status))
            settingsFile.write(ControlIniFile)
            ControlIniFile.close()
    except Exception as e:
        logfile ("Error writing settings file: %s" % e,"ERROR")
        traceback.print_exc()
        settings.restoreSettings()
        return oldvalue
    if settingsFile.has_section(section):
        params['value'] = status
        params['oldvalue'] = oldvalue
        if settingsFile.has_option(section, "command"):
            rawcommand = settingsFile.get(section, "command")
            params[commandName+' side-effect'] = True
            macros.eventList.add("%s-TRIGGER" % commandName,0,rawcommand,params)
        else:
            try:
                if status == "1":
                    rawcommand = settingsFile.get(section,"on")
                else:
                    rawcommand = settingsFile.get(section,"off")
                if rawcommand is not None:
                    params[commandName+' side-effect'] = True
                    macros.eventList.add("%s-TRIGGER" % commandName,0,rawcommand,params)
            except Exception as e:
                logfile("TRIGGER %s: A command or on/off pair is required" % commandName, "ERROR")
                logfile ("ERROR was %s" % e,"ERROR")
    elif settingsFile.has_section("LOGIC "+commandName):
        params[commandName+' side-effect'] = True
        macros.eventList.add("%s-LOGIC" % commandName,0,commandName,params)
        logfile ("Queued LOGIC branch: %s" % commandName,"LOG")
    return status

#- Use getStatus to read variables, either from the settings file or device
def getStatus(commandName, params):
    if '/' in commandName:
        (deviceName,commandName) = commandName.split('/')
        params = params.copy()
        params['device'] = deviceName
    else:
        deviceName = params["device"]
    sectionName = deviceName + " Status"

    device = devices.DeviceByName[deviceName]
    func = devices.Dev[deviceName]["getStatus"]
    if func is not None:
        #print ("getStatus func(%s) is %s" % (type(func),func))
        retval = func(device,deviceName,commandName,params)
        if retval is not False:
            if 'REDIRECT' in retval:
                (command,deviceName) = retval.split(' ',2)
                sectionName = deviceName + " Status"
            else:
                return retval
    if settingsFile.has_option(sectionName,commandName):
        status = settingsFile.get(sectionName, commandName)
        return status
    if settingsFile.has_option('Status',commandName):
        status = settingsFile.get('Status', commandName)
        params["globalVariable"] = commandName
        if status:
            return status
    logfile("Can't find %s %s" % (sectionName, commandName),"WARN")
    return "0"


def toggleStatus(commandName, params):
    status = getStatus(commandName,params)
    # print ("Status = %s" % status)
    try:
        if status == "0":
            setStatus(commandName,"1",params)
        else:
            setStatus(commandName,"0",params)
    except:
        pass
    return getStatus(commandName,params)


def getSensor(sensorName,params):
    if '/' in sensorName:
        (deviceName,sensorName) = sensorName.split('/')
        params = params.copy()
        params['device'] = deviceName
    else:
        deviceName = params['device']
    with devices.Dev[deviceName]['Lock']:
        func = devices.Dev[deviceName]["getSensor"]
        if func is not None:
            return func(sensorName,params)
    return False


def start(handler_class=Handler, port=8080, listen='0.0.0.0'):
    addr = (listen,port)
    if settings.Hostname == "localhost":
        name=''
    else:
        name = settings.Hostname + " "
    logfile ('\nStarting RestHome server %son %s:%s ...\n' % (name,listen,port),"SPECIAL")
    sock = socket.socket (socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(addr)
    sock.listen(5)
    devices.startUp(sock,addr,setStatus,getStatus,sendCommand,handler_class)
    while not threadpool.InterruptRequested.is_set():
        threadpool.InterruptRequested.wait(2)
    logfile("Closing Server ...", "SPECIAL")
    sock.close()


def readSettingsFile(settingsFile):
    global RestrictAccess
    global LearnFrom
    global OverwriteProtected
    global GlobalPassword
    global GlobalTimeout

    # A few defaults
    serverPort = 8080
    Autodetect = False
    OverwriteProtected = True
    listen_address = '0.0.0.0'
    broadcast_address = '255.255.255.255'

    settingsFile.optionxform = str
    with devices.SettingsLock:
        settingsFile.read(settings.settingsINI)

    GlobalTimeout = settings.GlobalTimeout
    DiscoverTimeout = settings.DiscoverTimeout

    # Override them
    if settingsFile.has_option('General', 'Password'):
        GlobalPassword = settingsFile.get('General', 'Password').strip()

    if settingsFile.has_option('General', 'ServerPort'):
        serverPort = int(settingsFile.get('General', 'ServerPort'))

    if settingsFile.has_option('General','ServerAddress'):
        listen_address = settingsFile.get('General', 'ServerAddress')
        if listen_address.strip() == '':
            listen_address = '0.0.0.0'

    if settingsFile.has_option('General', 'RestrictAccess'):
        RestrictAccess = settingsFile.get('General', 'RestrictAccess').strip()

    if settingsFile.has_option('General', 'LearnFrom'):
        LearnFrom = settingsFile.get('General', 'LearnFrom').strip();

    if settingsFile.has_option('General', 'AllowOverwrite'):
        OverwriteProtected = False

    if settingsFile.has_option('General','BroadcastAddress'):
        broadcast = settingsFile.get('General', 'BroadcastAddress')
        if broadcast_address.strip() == '':
            broadcast_address = '255.255.255.255'

    if settingsFile.has_option('General', 'Autodetect'):
        try:
            DiscoverTimeout = int(settingsFile.get('General', 'Autodetect').strip())
        except:
            DiscoverTimeout = 5
        Autodetect = True
        settingsFile.remove_option('General','Autodetect')

    # Device list
    if not devices.DevList:
        Autodetect = True

    if Autodetect == True:
        logfile ("Beginning device auto-detection ... ","LOG")
        # Try to support multi-homed broadcast better
        devices.discover(settingsFile,DiscoverTimeout,listen_address,broadcast_address)
        print()
        reloadAll()
        return None

    if devices.DevList:
        for devname in devices.DevList:
            devices.Dev[devname]['BaseType'] = 'unknown'
            device = devices.readSettings(settingsFile,devname)
            if device == None:
                devices.Dev[devname]['threads'] = 0
                continue
            if devices.Dev[devname]['BaseType'] != 'virtual':
                devtype = devices.Dev[devname]['Type']
                devices.Dev[devname]['Lock'] = threading.RLock()
            else:
                devtype = device.real

            if 'Comment' in devices.Dev[devname]:
                comment = ' (' + devices.Dev[devname]['Comment'].strip()+')'
            else:
                comment = ''
            logfile("Configured %s%s as %s/%s" % (devname,comment,devices.Dev[devname]['BaseType'],devtype),"WARN")
            if not devname in devices.DeviceByName:
                devices.DeviceByName[devname] = device
            #device.hostname = devname
            if hasattr(device, 'auth'):
                device.auth()
            if devices.Dev[devname]['StartupCommand'] != None:
                commandName = devices.Dev[devname]['StartupCommand']
                query = {}
                query["device"] = devname
                macros.eventList.add("Startup "+devname,1,commandName,query)

    return { "port": serverPort, "listen": listen_address }


def SigUsr1(signum, frame):
    logfile ("\nReload requested ... (this will take awhile)","LOG")
    threadpool.InterruptRequested.set()


def SigInt(signum, frame):
    if threadpool.InterruptRequested.is_set():
        print ("\n\nAborting!\n")
        exit()
    logfile ("\nShuting down server ...","SPECIAL")
    threadpool.ShutdownRequested.set()
    threadpool.InterruptRequested.set()


if __name__ == "__main__":
    if platform.system() != "Windows":
        signal.signal(signal.SIGUSR1,SigUsr1)
        signal.signal(signal.SIGINT,SigInt)
    while not threadpool.ShutdownRequested.is_set():
        threadpool.InterruptRequested.clear()
        settingsFile = configparser.ConfigParser()
        serverParams = None
        while serverParams is None:
            serverParams = readSettingsFile(settingsFile)
        macros.init_callbacks(settingsFile,sendCommand,getStatus,setStatus,toggleStatus)
        start(**serverParams)
        logfile("\nShutting down devices ...")
        for devname in devices.DeviceByName:
            if devices.Dev[devname]['ShutdownCommand'] != None:
                commandName = devices.Dev[devname]['ShutdownCommand']
                query = {}
                query["device"] = devname
                query["command"] = commandName
                query['serialize'] = True
                if 'Delay' in devices.Dev[devname]:
                    query['deviceDelay'] = float(devices.Dev[devname]['Delay'])
                else:
                    query['deviceDelay'] = 0.2
                sendCommand(commandName,query)
        if not threadpool.ShutdownRequested.is_set():
            time.sleep(20)
            logfile ("Reloading configuration ...\n","WARN")
            reloadAll()
    devices.shutDown(setStatus,getStatus)
