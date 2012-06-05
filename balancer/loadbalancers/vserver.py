# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

#import balancer.common.utils
import logging
#import pdb
import openstack.common.exception
#from balancer.loadbalancers.command import BaseCommand

import loadbalancer
import predictor
import probe
#import realserver
#import serverfarm
#import virtualserver
import sticky

from balancer.db import api as db_api
from balancer import exception


logger = logging.getLogger(__name__)


class Balancer():
    def __init__(self, conf):

        """ This member contains LoadBalancer object """
        self.lb = None
        self.sf = None
        self.rs = []
        self.probes = []
        self.vips = []
        self.conf = conf

    def parseParams(self, params):
        obj_dict = params.copy()
        nodes_list = obj_dict.pop('nodes') or []
        probes_list = obj_dict.get('healthMonitor') or []
        vips_list = obj_dict.get('virtualIps') or []
        stic = obj_dict.get('sessionPersistence') or []

        lb_ref = db_api.loadbalancer_pack_extra(obj_dict)
        lb_ref['status'] = loadbalancer.LB_BUILD_STATUS
        self.lb = lb_ref

        sf_ref = db_api.serverfarm_pack_extra({})
        sf_ref['name'] = sf_ref['id']
        sf_ref['lb_id'] = lb_ref['id']
        self.sf = sf_ref
        self.sf._rservers = []
        self.sf._probes = []
        self.sf._sticky = []

        predictor_ref = db_api.predictor_pack_extra({})
        predictor_ref['type'] = lb_ref['algorithm']
        predictor_ref['sf_id'] = sf_ref['id']
        self._predictor = predictor_ref

        """ Parse RServer nodes and attach them to SF """
        for node in nodes_list:
            rs_ref = db_api.server_pack_extra(node)
            # We need to check if there is already real server with the
            # same IP deployed
            try:
                parent_ref = db_api.server_get_by_address(self.conf,
                                                          rs_ref['address'])
            except exception.ServerNotFound:
                pass
            else:
                if parent_ref['address'] != '':
                    rs_ref['parent_id'] = parent_ref['id']
            rs_ref['sf_id'] = sf_ref['id']
            rs_ref['name'] = rs_ref['id']

            self.rs.append(rs_ref)
            self.sf._rservers.append(rs_ref)

        for pr in probes_list:
            probe_ref = db_api.probe_pack_extra(pr)
            probe_ref['sf_id'] = sf_ref['id']
            probe_ref['name'] = probe_ref['id']

            self.probes.append(probe_ref)
            self.sf._probes.append(probe_ref)

        for vip in vips_list:
            vs_ref = db_api.virtualserver_pack_extra(vip)
            vs_ref['transport'] = lb_ref['extra']['transport']
            vs_ref['appProto'] = lb_ref['protocol']
            vs_ref['sf_id'] = sf_ref['id']
            vs_ref['lb_id'] = lb_ref['id']
            vs_ref['name'] = vs_ref['id']
            self.vips.append(vs_ref)
            self.vips.append(vs_ref)

# NOTE(ash): broken
#        if stic != None:
#            for st in stic:
#                st = createSticky(stic['type'])
#                st.loadFromDict(stic)
#                st.sf_id = sf.id
#                st.name = st.id
#                self.sf._sticky.append(st)

    def update(self):
        db_api.loadbalancer_update(self.conf, self.lb['id'], self.lb)

        for st in self.sf._sticky:
            db_api.sticky_update(self.conf, st['id'], st)
        for rs in self.rs:
            db_api.server_update(self.conf, rs['id'], rs)
        for pr in self.probes:
            db_api.probe_update(self.conf, pr['id'], pr)
        for vip in self.vips:
            db_api.virtualserver_update(self.conf, vip['id'], vip)

    def getLB(self):
        return self.lb

    def savetoDB(self):
        lb_ref = db_api.loadbalancer_create(self.conf, self.lb)
        sf_ref = db_api.serverfarm_create(self.conf, self.sf)
        db_api.predictor_create(self.conf, self.sf._predictor)

        for rs in self.rs:
            db_api.server_create(self.conf, rs)

        for pr in self.probes:
            db_api.probe_create(self.conf, pr)

        for vip in self.vips:
            db_api.virtualserver_create(self.conf, vip)

        for st in self.sf._sticky:
            db_api.sticky_create(self.conf, st)

    def loadFromDB(self, lb_id):
        self.lb = db_api.loadbalancer_get(self.conf, lb_id)
        self.sf = db_api.serverfarm_get_all_by_lb_id(self.conf, lb_id)[0]
        sf_id = self.sf['id']
        predictor = db_api.predictor_get_all_by_sf_id(self.conf, sf_id)[0]
        self.sf._predictor = predictor
        self.rs = db_api.server_get_all_by_sf_id(self.conf, sf_id)
        sticks = db_api.sticky_get_all_by_sf_id(self.conf, sf_id)

        for rs in self.rs:
            self.sf._rservers.append(rs)
        self.probes = db_api.probe_get_all_by_sf_id(sf_id)
        for prob in self.probes:
            self.sf._probes.append(prob)
        self.vips = db_api.virtualserver_get_all_by_sf_id(sf_id)
        for st in sticks:
            self.sf._sticky.append(st)

    def removeFromDB(self):
        lb_id = self.lb['id']
        sf_id = self.sf['id']
        db_api.loadbalancer_destroy(self.conf, lb_id)
        db_api.serverfarm_destroy(self.conf, sf_id)
        db_api.predictor_destroy_by_sf_id(self.conf, sf_id)
        db_api.server_destroy_by_sf_id(self.conf, sf_id)
        db_api.probe_destroy_by_sf_id(self.conf, sf_id)
        db_api.virtualserver_destroy_by_sf_id(self.conf, sf_id)
        db_api.sticky_destroy_by_sf_id(self.conf, sf_id)


#    def deploy(self,  driver,  context):
#        #Step 1. Deploy server farm
#        if  driver.createServerFarm(context,  self.sf) != "OK":
#            raise exception.OpenstackException
#
#        #Step 2. Create RServers and attach them to SF
#
#        for rs in self.rs:
#            driver.createRServer(context,  rs)
#            driver.addRServerToSF(context,  self.sf,  rs)
#
#        #Step 3. Create probes and attache them to SF
#        for pr in self.probes:
#            driver.createProbe(context,  pr)
#            driver.addProbeToSF(context,  self.sf,  pr)
#        #Step 4. Deploy vip
#        for vip in self.vips:
#            driver.createVIP(context,  vip,  self.sf)


def createProbe(probe_type):
    probeDict = {'DNS': probe.DNSprobe(), 'ECHO TCP': probe.ECHOTCPprobe(),
                'ECHO UDP': probe.ECHOUDPprobe(), 'FINGER': probe.FINGERprobe(),
                'FTP': probe.FTPprobe(), 'HTTPS': probe.HTTPSprobe(),
                'HTTP': probe.HTTPprobe(), 'ICMP': probe.ICMPprobe(),
                'IMAP': probe.IMAPprobe(), 'POP': probe.POPprobe(),
                'RADIUS': probe.RADIUSprobe(), 'RTSP': probe.RTSPprobe(),
                'SCRIPTED': probe.SCRIPTEDprobe(),
                'SIP TCP': probe.SIPTCPprobe(),
                'SIP UDP': probe.SIPUDPprobe(), 'SMTP': probe.SMTPprobe(),
                'SNMP': probe.SNMPprobe(), 'CONNECT': probe.TCPprobe(),
                'TELNET': probe.TELNETprobe(), 'UDP': probe.UDPprobe(),
                'VM': probe.VMprobe()}
    obj = probeDict.get(probe_type,  None)
    if obj == None:
        raise openstack.common.exception.Invalid("Can't create health \
			   monitoring probe of type %s" % probe_type)
    return obj.createSame()


def createPredictor(pr_type):
    predictDict = {'HashAddr': predictor.HashAddrPredictor(),
                  'HashContent': predictor.HashContent(),
                  'HashCookie': predictor.HashCookie(),
                  'HashHeader': predictor.HashHeader(),
                  'HashLayer4': predictor.HashLayer4(),
                  'HashURL': predictor.HashURL(),
                  'LeastBandwidth': predictor.LeastBandwidth(),
                  'LeastConnections': predictor.LeastConn(),
                  'LeastLoaded': predictor.LeastLoaded(),
                  'Response': predictor.Response(),
                  'RoundRobin': predictor.RoundRobin()}

    obj = predictDict.get(pr_type,  None)
    if obj == None:
        raise openstack.common.exception.Invalid("Can't find load balancing \
                                           algorithm with type %s" % pr_type)
    return obj.createSame()


def createSticky(st_type):
    stickyDict = {'http-content': sticky.HTTPContentSticky(), \
                        'http-cookie': sticky.HTTPCookieSticky(), \
                        'http-header': sticky.HTTPHeaderSticky(), \
                        'ip-netmask': sticky.IPNetmaskSticky(), \
                        'layer4-payload': sticky.L4PayloadSticky(), \
                        'rtsp-header': sticky.RTSPHeaderSticky(), \
                        'radius': sticky.RadiusSticky(), \
                        'sip-header': sticky.SIPHeaderSticky(), \
                        'v6prefix': sticky.v6PrefixSticky()}

    obj = stickyDict.get(st_type,  None)
    if obj == None:
        raise openstack.common.exception.Invalid("Can't find load balancing \
                                           algorithm with type %s" % st_type)
    return obj.createSame()
