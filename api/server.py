# python 3.7.3

###################################
# Developer: Josh Spencer         #
# Email: jaspencer14@gmail.com    #
###################################

##################################################################################
# To successfully run the code, the following libraries have to be installed     #
# To do this, you can use a package manager like pip                             #
# https://packaging.python.org/tutorials/installing-packages/                    #
##################################################################################
from http.server import BaseHTTPRequestHandler, HTTPServer
import socketserver
from os import path
import time
from io import BytesIO
import json
from subprocess import check_output

###################################
# Import my api utilization code  #
###################################
from citrix.citrix import *

####################################################
# If desired, hostName and hostPort can be changed #
####################################################
hostName = "localhost"
hostPort = 8080

##################################################################################
# This class, which is instantiated by main(), sets up the server. To add a      #
#   new GET endpoint to the API, add it to the do_GET function. Likewise with    #
#   types of requests such as POST, PUT, DELETE.
##################################################################################

class MyServer(BaseHTTPRequestHandler):

##################################################################################
# Currently the only implemented GET requests are for files. To add more,        #
#   route requests to function through the requestPath variable                  #
##################################################################################

    def do_GET(self):
        requestPath = self.path

        self.send_response(200)

        if ".css" in requestPath:
            self.send_header("Content-type", "text/css")
        elif ".js" in requestPath:
            self.send_header("Content-type", "text/javascript")
        else:
            self.send_header("Content-type", "text/html")

        self.end_headers()

        if requestPath == "/":
            requestPath = "/index.html"

        filePath = "./static" + requestPath
        data = None

        if not path.exists(filePath):
            filePath = "./static/index.html"

        file = open(filePath, 'rb')
        data = file.read()
        file.close()

        self.wfile.write(data)

##################################################################################
# Currently the only implemented POST request is to create the lb resources.     #
# To change this, route request to function through the requestPath variable.    #
##################################################################################

    def do_POST(self):

        if self.path == "/api/standardLoadBalRequest":
            self.handle_StandardLoadBalRequest()
        else:
            content_length = int(self.headers['Content-Length'])

            self.send_response(200)
            self.end_headers()

            response = BytesIO()
            response.write(b'{\"message\":\"no endpoint to handle request\"}')
            self.wfile.write(response.getvalue())


    def handle_StandardLoadBalRequest(self):
        content_length = int(self.headers['Content-Length'])

        # Decode request str to a json dictionary
        bodyBinary = self.rfile.read(content_length)
        bodyStr = bodyBinary.decode('utf-8')
        bodyJson = json.loads(bodyStr)

        # Create servers, service groups, and lbVServers; Bind everything together
        self.implement_StandardLoadBalRequest(bodyJson)

        self.send_response(200)
        self.end_headers()

        response = BytesIO()
        response.write(b'{\"handled\":\"it\"}')
        self.wfile.write(response.getvalue())

    def implement_StandardLoadBalRequest(self, bodyJson):

        appName = bodyJson["appName"] # Get the appName from the request

        dataCenter = bodyJson["dataCenter"] # Get the desired data center from the request

        networkZone = bodyJson["networkZone"] # Get the network zone from the request

        hostnameTableEntries = bodyJson["hostnameTableEntries"] # Get the hostname table entries from the request

        # Create Servers
        createdServers = self.create_servers(appName, hostnameTableEntries)

        # Create Service Groups
        createdServiceGroups = self.create_serviceGroups(appName, hostnameTableEntries)

        # Bind servers to service groups
        self.bind_serversToServiceGroups(createdServers, createdServiceGroups)

        createdLbVServers = self.create_lbVServer(appName, createdServers)

        self.bind_serviceGroupsToLbVServers(createdServiceGroups, createdLbVServers)

        # LB used for lbvserver
        lbMethod = bodyJson["loadBalanceMethod"]

        lbPersistencyType = bodyJson["loadBalancePersistencyType"]

        lbPersistencyTimeout = bodyJson["loadBalancePersistencyTimeout"]

        comments = bodyJson["comments"]

    def create_servers(self, appName, hostnameTableEntries):

        createdServers = []
        # Iterate through hostnameTableEntries to create servers
        for entry in hostnameTableEntries:

            # Get ip address from nslookup of serverName
            serverName = entry['serverName']
            ip = self.nslookup(serverName)

            if ip == None:
                print("Server ({}) does not have a valid IP address!".format(serverName))
                continue

            # Create newServerName from appName and serverPort
            serverPort = entry['serverPort']
            vipPort = entry['vipPort']
            protocol = entry['protocol']

            newServerName = "{}-{}".format(serverName, serverPort)

            # Create new server with newServerName and ip address
            print("newServerName: {}".format(newServerName))
            print("ip: {}".format(ip))
            print()

            ####################################
            # CONNECT TO FUNCTION IN citrix.py #
            ####################################

            # Add server to list of created servers
            createdServers.append({"serverName":newServerName, "protocol":protocol, "serverPort": serverPort, "vipPort": vipPort})

        return createdServers

    def nslookup(self, serverName):
        nsRetBinary = check_output("nslookup {} 2> nul".format(serverName), shell=True) # Perform nslookup and through out stderr
        nsRetAscii = nsRetBinary.decode("ascii") # Convert binary to ascii
        nsRetLines = nsRetAscii.splitlines() # Split into dict by lines
        nsRetLines = nsRetLines[3:] # Take off unnecessary entries
        nsRetLines = [line.replace(" ","") for line in nsRetLines] # Remove spaces from lines

        nsRetDict = {}

        # Create a dictionary from nslookup return
        for line in nsRetLines:
            if line == "":
                continue
            else:
                lineParts = line.split(":")

                if len(lineParts) != 2:
                    continue
                else:
                    nsRetDict[lineParts[0]] = lineParts[1]

        # Check to see if there is an address in the dictionary
        if "Address" not in nsRetDict.keys():
            return None
        else:
            return nsRetDict["Address"]

    def create_serviceGroups(self, appName, createdServers):
        createdServiceGroups = []
        requiredServiceGroups = {}

        for server in createdServers:
            if server['serverPort'] in requiredServiceGroups.keys():
                 requiredServiceGroups[server['serverPort']].add(server['protocol'])
            else:
                requiredServiceGroups[server['serverPort']] = set()
                requiredServiceGroups[server['serverPort']].add(server['protocol'])

        for port in requiredServiceGroups.keys():
            # Check to see if server port is overloaded
            if len(requiredServiceGroups[port]) != 1:
                print("Server Port {} is overloaded!".format(port))
                continue
            else:
                serviceGroupName = "sg-{}-{}".format(appName, port)
                serviceType = list(requiredServiceGroups[port])[0]

                for server in createdServers:
                    if server['serverPort'] == port:
                        vipPort = server['vipPort']

                # Create new service group with serviceGroupName and serviceType
                print("serviceGroupName: {}".format(serviceGroupName))
                print("serviceType: {}".format(serviceType))
                print()

                ####################################
                # CONNECT TO FUNCTION IN citrix.py #
                ####################################


                # Add service group to list of created service groups
                createdServiceGroups.append({"serviceGroupName":serviceGroupName,"serviceType":serviceType,"serverPort":port, "vipPort":vipPort})

        return createdServiceGroups

    def bind_serversToServiceGroups(self, createdServers, createdServiceGroups):

        for server in createdServers:
            serverName = server["serverName"]
            serverPort = server["serverPort"]

            for serviceGroup in createdServiceGroups:
                if serviceGroup["serverPort"] == serverPort:
                    serviceGroupName = serviceGroup["serviceGroupName"]
                    print("Bind: {} - {} - {}".format(serviceGroupName, serverName, serverPort))
                    print()

                    ####################################
                    # CONNECT TO FUNCTION IN citrix.py #
                    ####################################

                    break
        return

    def create_lbVServer(self, appName, createdServers):
        createdLbVServers = []
        requiredLbVServers = {}

        for server in createdServers:
            if server['vipPort'] in requiredLbVServers.keys():
                 requiredLbVServers[server['vipPort']].add(server['protocol'])
            else:
                requiredLbVServers[server['vipPort']] = set()
                requiredLbVServers[server['vipPort']].add(server['protocol'])

        for port in requiredLbVServers.keys():
            # Check to see if server port is overloaded
            if len(requiredLbVServers[port]) != 1:
                print("Vip Port {} is overloaded!".format(port))
                continue
            else:
                lbVServerName = "lb-{}-{}".format(appName, port)
                serviceType = list(requiredLbVServers[port])[0]

                # TODO: Get ip from InfoBlox
                ipv46 = self.getIpFromInfoblox()

                # Create new lbVServer with the lbVServerName, serviceType, port, and ipv46 from InfoBlox
                print("lbVServerName: {}".format(lbVServerName))
                print("serviceType: {}".format(serviceType))
                print("ipv46: {}".format(ipv46))
                print("port: {}".format(port))
                print()

                ####################################
                # CONNECT TO FUNCTION IN citrix.py #
                ####################################


                # Add lbVServer to list of created lbVServers
                createdLbVServers.append({"lbVServerName":lbVServerName,"serviceType":serviceType, "ipv46":ipv46, "vipPort":port})

        return createdLbVServers

    #################################
    # TODO: Integrate with Infoblox #
    #################################
    def getIpFromInfoblox(self):
        return "10.10.10.10"

    def bind_serviceGroupsToLbVServers(self, createdServiceGroups, createdLbVServers):

        for serviceGroup in createdServiceGroups:
            serviceGroupName = serviceGroup["serviceGroupName"]
            serviceGroupVipPort = serviceGroup["vipPort"]

            for lbVServer in createdLbVServers:
                if lbVServer['vipPort'] == serviceGroupVipPort:
                    lbVServerName = lbVServer["lbVServerName"]

                    print("Bind: {} - {} - {}".format(serviceGroupName, lbVServerName, serviceGroupVipPort))
                    print()

                    ####################################
                    # CONNECT TO FUNCTION IN citrix.py #
                    ####################################

                    break

def main():

    myServer = HTTPServer((hostName, hostPort), MyServer)

    print("Serving on port {} ...".format(hostPort))

    try:
        myServer.serve_forever()
    except KeyboardInterrupt:
        pass

    myServer.server_close()


if __name__ == "__main__":
    main()
