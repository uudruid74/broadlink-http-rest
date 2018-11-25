#!/usr/bin/python3.4
from termcolor import cprint
from os import path
from importlib import reload
import devices
import settings
import traceback
import datetime
import threading
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
import http.server

import device_broadlink
import device_url

def reloadAll():
    reload(devices)
    reload(device_broadlink)
    reload(device_url)
    reload(settings)

THROTTLE = 4    #- spawn per second


class Thread(threading.Thread):
    def __init__(self, i, sock, addr, timeout):
        threading.Thread.__init__(self)
        self.i = i
        self.sock = sock
        self.addr = addr
        self.timeout = timeout
        self.daemon = True
        time.sleep(self.i/THROTTLE)
        self.start()
    def run(self):
        httpd = http.server.HTTPServer(self.addr, Handler, False)

        # Prevent the HTTP server from re-binding every handler.
        # https://stackoverflow.com/questions/46210672/
        httpd.socket = self.sock
        httpd.server_bind = self.server_close = lambda self: None
        while not InterruptRequested.is_set():
            timer = min(self.timeout,macros.eventList.nextEvent())
            while timer < 1:
                event = macros.eventList.pop()
                cprint ("EVENT (%s) %s" % (datetime.datetime.now().strftime("%I:%M:%S"),event.name),"blue")
                sendCommand(event.command,event.params)
                print ('')
                timer = min(self.timeout,macros.eventList.nextEvent())
            httpd.timeout = timer
            httpd.handle_request()


class Handler(http.server.BaseHTTPRequestHandler):
    Parameters = collections.defaultdict(lambda : ' ')
    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin','*')
        self.end_headers()

    def do_GET(self):
        try:
            if GlobalPassword:
                try:
                    if RestrictAccess and self.client_address[0] not in RestrictAccess:
                        return self.access_denied()
                    return self.messageHandler()
                except NameError as e:
                    cprint ("Error: %s" % e,"yellow")
                    self.password_required()
        except NameError:                   #- No security specified
            self.messageHandler()

    def do_POST(self):
        password = ''
        try:
            content_len = int(self.headers.get('content-length', 0))
            self.Parameters.update(json.loads(self.rfile.read(content_len).decode("utf-8")))
            password = self.Parameters['password'];
        except:
            traceback.print_exc()
            pass
        try:
            if GlobalPassword and GlobalPassword == password:
                return self.messageHandler()
            else:
                cprint ('''POST Password Wrong: "%s"''' % password,"red")
        except NameError:
                return self.password_required()
        self.password_required()

    def password_required(self):
        response = "POST Password required from %s" % self.client_address[0]
        self.wfile.write(bytes('''{ "error": "%s" }''' % response,'utf-8'))
        cprint (response,"red")
        self.close_connection = 1
        return False

    def access_denied(self):
        response = "Client %s is not allowed to use GET!" % self.client_address[0]
        self.wfile.write(bytes('''{ "error": "%s" }''' % response,'utf-8'))
        cprint (response,"red")
        self.close_connection = 1
        return False

    def messageHandler(self):
        if 'favicon' in self.path:
            return False

        self._set_headers()
        if '?' in self.path:
            (self.path,query) = self.path.split('?')
            params = re.split('[&=]+',query)
            for index in range(0,len(params),2):
                self.Parameters[params[index]] = params[index+1]
        paths = re.split('[//=]+',self.path)
        if 'learnCommand' in self.path:
            try:
                if self.client_address[0] not in LearnFrom:
                    cprint ("Won't learn commands from %s.  Access Denied!" % self.client_address[0],"red",attrs=['bold'])
                    return False
            except NameError:
                pass

            if paths[2] == 'learnCommand':
                deviceName = paths[1]
                commandName = paths[3]
            else:
                commandName = paths[2]
                deviceName = None
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
                deviceName = None
            self.Parameters["device"] = deviceName
            result = sendCommand(commandName, self.Parameters)
            if result == False:
                response = "Failed: Unknown command - %s" % commandName
            elif result == True:
                response = commandName
            else:
                response = result

        elif 'getStatus' in self.path:
            if paths[2] == 'getStatus':
                commandName = paths[3]
                deviceName = paths[1]
            else:
                commandName = paths[2]
                deviceName = None
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
                deviceName = None
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
                deviceName = None
            self.Parameters["device"] = deviceName
            status = toggleStatus(commandName, self.Parameters)
            if (status):
                response = '''{ "%s": "%s" }''' % (commandName, status)
            else:
                response = "Failed: Unknown command - %s"% commandName

        elif 'getSensor' in self.path:
            if paths[2] == 'getSensor':
                sensor = paths[3]
                deviceName = paths[1]
            else:
                sensor = paths[2]
                deviceName = None
            self.Parameters["device"] = deviceName
            result = getSensor(sensor, self.Parameters)
            if result == False:
                response = "Failed to get data"
            else:
                response = '''{ "%s": "%s" }''' % (sensor, result)
        else:
            response = "Failed"
        if "Failed" in response or "error" in response:
            self.wfile.write(bytes('''{ "error": "%s" }''' % response,'utf-8'))
        elif response.startswith('{'):
            self.wfile.write(bytes(response,'utf-8'))
        else:
            self.wfile.write(bytes('''{ "ok": "%s" }''' % response,'utf-8'))
        cprint ("\t"+response,"white")
        print("")


def sendCommand(commandName,params):
    deviceName = params["device"]
    #print '''SendCommand: %s to "%s"''' % (commandName,deviceName)
    if deviceName == None:
        device = devices.deviceStore[0]
        serviceName = 'Commands'
    elif deviceName in devices.DeviceByName:
        device = devices.DeviceByName[deviceName]
        serviceName = deviceName + ' Commands'
    else:
        return "Failed: No such device, %s" % deviceName
    if "deviceDelay" not in params:
        params["deviceDelay"] = devices.Dev[deviceName]["Delay"]
    if params["deviceDelay"] == None:
        params["deviceDelay"] = 0.2
    params["command"] = commandName #- VERY IMPORTANT!

    if commandName.strip() != '':
        result = macros.checkConditionals(commandName,params)
        #print ("checkCond result: %s = %s" % (commandName,result))
        if result:
            return result

        command = False
        newCommandName = False
        if 'PRINT' not in commandName and 'MACRO' not in commandName:
            if commandName.endswith("on"):
                newCommandName = commandName[:-2]
                setStatus(newCommandName, '1', params)
            elif commandName.endswith("off"):
                newCommandName = commandName[:-3]
                setStatus(newCommandName, '0', params)

        if settingsFile.has_option(serviceName, commandName):
            command = settingsFile.get(serviceName, commandName)
        elif settingsFile.has_option('Commands', commandName):
            command = settingsFile.get('Commands', commandName)
        elif settingsFile.has_option(serviceName, newCommandName):
            command = settingsFile.get(serviceName, newCommandName)
        elif settingsFile.has_option('Commands', newCommandName):
            command = settingsFile.get('Commands', newCommandName)

        if command is False:
            result = macros.checkMacros(commandName,params)
        else:
            result = macros.checkMacros(command,params)
        if result:
            return result

        with devices.Dev[deviceName]['Lock']:
            devices.Dev[deviceName]['sendCommand'](command,device,deviceName,params)
        return commandName


def learnCommand(commandName, params):
    print ("learnCommand called")
    deviceName = params["device"]
    print ("Got DeviceName")
    try:
        if deviceName == None:
            device = devices.deviceStore[0]
            sectionName = 'Commands'
        elif deviceName in devices.DeviceByName:
            device = devices.DeviceByName[deviceName];
            sectionName = deviceName + ' Commands'
        else:
            return "Failed: No such device, %s" % deviceName

        print ("Checking Overwrite")
        if OverwriteProtected and settingsFile.has_option(sectionName,commandName):
            cprint ("Command %s alreadyExists and changes are protected!" % commandName,"yellow")
            return False
    except:
        traceback.print_exc()

    print ("Locking device")
    with devices.Dev[deviceName]['Lock']:
        cprint ("Waiting %d seconds to capture command" % GlobalTimeout,"magenta")

        decodedCommand = devices.Dev[deviceName]['learnCommand'](deviceName,device)
        settings.backupSettings()
        try:
            ControlIniFile = open(path.join(settings.applicationDir, 'settings.ini'), 'w')
            if not settingsFile.has_section(sectionName):
                settingsFile.add_section(sectionName)
            settingsFile.set(sectionName, commandName, str(decodedCommand,'utf8'))
            settingsFile.write(ControlIniFile)
            ControlIniFile.close()
            return commandName
        except Exception as e:
            cprint("Error writing settings file: %s" % e,"yellow")
            traceback.print_exc()
            settings.restoreSettings()
    return False


#- The setStatus command is not designed to perform actions, use sendCommand
#- instead with on/off appended or pass a parameter.  Use setStatus for
#- setting variables.
def setStatus(commandName, status, params):
    deviceName = params["device"]
    sectionName = 'Status'
    if deviceName is not None and ('globalVariable' not in params or params['globalVariable'] is not commandName):
        sectionName = deviceName + " Status"

    #print "command = %s status = %s devicename = %s section = %s" % (commandName, status, deviceName, sectionName)
    settings.backupSettings()
    oldvalue = getStatus(commandName,params)
    if oldvalue == status:
        cprint ("Value of %s not changed: %s" % (commandName, status), "green")
        return oldvalue
    if settingsFile.has_section("SET "+commandName):
        section = "SET " + commandName
        if settingsFile.has_option(section, "trigger"):
            rawcommand = settingsFile.get(section, "trigger")
            macros.eventList.add("TRIGGER %s" % commandName,0,rawcommand,params)
        else:
            try:
                #print("TEST returned %s" % value)
                if status == "1":
                    rawcommand = settingsFile.get(section,"on")
                else:
                    rawcommand = settingsFile.get(section,"off")
                #print ("Raw %s: %s" % (commandName,rawcommand))
                macros.eventList.add("TRIGGER %s" % commandName,0,rawcommand,params)
            except Exception as e:
                cprint("SET %s: A trigger or on/off pair is required" % commandName, "yellow")
                cprint ("ERROR was %s" % e,"yellow")
    elif settingsFile.has_section("LOGIC "+commandName):
        macros.eventList.add("LOGIC %s" % commandName,0,commandName,params)
        cprint ("Queued LOGIC branch: %s" % commandName,"cyan")
    func = devices.Dev[deviceName]["setStatus"]
    if func is not None:
        retval = func(deviceName,commandName,params)
    try:
        if not settingsFile.has_section(sectionName):
            settingsFile.add_section(sectionName)
        ControlIniFile = open(path.join(settings.applicationDir, 'settings.ini'), 'w')
        settingsFile.set(sectionName, commandName, str(status))
        settingsFile.write(ControlIniFile)
        ControlIniFile.close()
        return oldvalue
    except Exception as e:
        cprint ("Error writing settings file: %s" % e,"yellow")
        traceback.print_exc()
        settings.restoreSettings()
        return False


#- Use getStatus to read variables, either from the settings file or device
def getStatus(commandName, params):
    deviceName = params["device"]
    sectionName = 'Status'
    if deviceName is not None:
        sectionName = deviceName + " Status"

    func = devices.Dev[deviceName]["getStatus"]
    if func is not None:
        print ("getStatus func(%s) is %s" % (type(func),func))
        retval = func(deviceName,commandName,params)
        if retval is not False:
            return retval
    if settingsFile.has_option(sectionName,commandName):
        status = settingsFile.get(sectionName, commandName)
        return status
    if settingsFile.has_option('Status',commandName):
        status = settingsFile.get(sectionName, commandName)
        params["globalVariable"] = commandName
        return status
    status = getSensor(commandName,params)
    if status:
        return status
    else:
        # print ("Can't find %s %s" % (sectionName, commandName))
        return False


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
    deviceName = params["device"]
    if deviceName == None:
        device = devices.deviceStore[0]
    elif deviceName in devices.DeviceByName:
        device = devices.DeviceByName[deviceName]
    else:
        return "Failed: No such device, %s" % deviceName

    with devices.Dev[deviceName]['Lock']:
        func = devices.Dev[deviceName]["getSensor"]
        if func is not None:
            return func(device,deviceName,sensorName,params)
    return False


def start(handler_class=Handler, threads=8, port=8080, listen='0.0.0.0', timeout=20):
    addr = (listen,port)
    cprint ('\nStarting broadlink-rest server on %s:%s ...' % (listen,port),"green")
    sock = socket.socket (socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(addr)
    sock.listen(5)

    [Thread(i,sock,addr,timeout) for i in range(threads)]
    while not InterruptRequested.is_set():
        InterruptRequested.wait(timeout)
    cprint("Closing Server ...", "green")
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
    settingsFile.read(settings.settingsINI)

    GlobalTimeout = settings.GlobalTimeout
    DiscoverTimeout = settings.DiscoverTimeout

    # Override them
    if settingsFile.has_option('General', 'password'):
        GlobalPassword = settingsFile.get('General', 'password').strip()

    if settingsFile.has_option('General', 'serverPort'):
        serverPort = int(settingsFile.get('General', 'serverPort'))

    if settingsFile.has_option('General','serverAddress'):
        listen_address = settingsFile.get('General', 'serverAddress')
        if listen_address.strip() == '':
            listen_address = '0.0.0.0'

    if settingsFile.has_option('General', 'restrictAccess'):
        RestrictAccess = settingsFile.get('General', 'restrictAccess').strip()

    if settingsFile.has_option('General', 'MaxThreads'):
        MaxThreads = settingsFile.get('General','MaxThreads')
    else:
        MaxThreads = 8
    if settingsFile.has_option('General', 'learnFrom'):
        LearnFrom = settingsFile.get('General', 'learnFrom').strip();

    if settingsFile.has_option('General', 'allowOverwrite'):
        OverwriteProtected = False

    if settingsFile.has_option('General','broadcastAddress'):
        broadcast = settingsFile.get('General', 'broadcastAddress')
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
        cprint ("Beginning device auto-detection ... ","cyan")
        # Try to support multi-homed broadcast better
        devices.discover(settingsFile,DiscoverTimeout,listen_address,broadcast_address)
        print()
        reloadAll()
        return None

    if devices.DevList:
        for devname in devices.DevList:
            device = devices.readSettings(devname)
            devices.Dev[devname]['Lock'] = threading.RLock()
            print("Setting %s to Type %s" % (devname,devices.Dev[devname]['Type']))
            if not devname in devices.DeviceByName:
                devices.DeviceByName[devname] = device
            #device.hostname = devname
            if hasattr(device, 'auth'):
                device.auth()
            devices.deviceStore.append(device)
            if devices.Dev[devname]['StartUpCommand'] != None:
                commandName = devices.Dev[devname]['StartUpCommand']
                query = {}
                query["device"] = devname
                macros.eventList.add("StartUp"+commandName,1,commandName,query)

    return { "port": serverPort, "listen": listen_address, "threads": MaxThreads, "timeout": GlobalTimeout }


def SigUsr1(signum, frame):
    cprint ("\nReload requested ... (this will take awhile)","cyan")
    InterruptRequested.set()


def SigInt(signum, frame):
    cprint ("\nShuting down server ...","cyan")
    ShutdownRequested.set()
    InterruptRequested.set()


if __name__ == "__main__":
    ShutdownRequested = threading.Event()
    InterruptRequested = threading.Event()

    if platform.system() != "Windows":
        signal.signal(signal.SIGUSR1,SigUsr1)
        signal.signal(signal.SIGINT,SigInt)
    while not ShutdownRequested.is_set():
        InterruptRequested.clear()
        settingsFile = configparser.ConfigParser()
        serverParams = None
        while serverParams is None:
            serverParams = readSettingsFile(settingsFile)
        macros.init_callbacks(settingsFile,sendCommand,getStatus,setStatus,toggleStatus)
        devices.startUp()
        start(**serverParams)
        if not ShutdownRequested.is_set():
            time.sleep(18)
            cprint ("Reloading configuration ...\n","cyan")
            reloadAll()
    devices.shutDown()
