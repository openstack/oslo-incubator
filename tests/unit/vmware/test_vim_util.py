# Copyright (c) 2013 VMware, Inc.
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

"""
Unit tests for VMware API utility module.
"""

import mock

from openstack.common import test
from openstack.common.vmware import vim_util


class VimUtilTest(test.BaseTestCase):
    """Test class for utility methods in vim_util."""

    def test_get_moref(self):
        moref = vim_util.get_moref("vm-0", "VirtualMachine")
        self.assertEqual(moref.value, "vm-0")
        self.assertEqual(moref.type, "VirtualMachine")

    def test_build_selection_spec(self):
        client_factory = mock.Mock()
        sel_spec = vim_util.build_selection_spec(client_factory, "test")
        self.assertEqual(sel_spec.name, "test")

    def test_build_traversal_spec(self):
        client_factory = mock.Mock()
        sel_spec = mock.Mock()
        traversal_spec = vim_util.build_traversal_spec(client_factory,
                                                       'dc_to_hf',
                                                       'Datacenter',
                                                       'hostFolder', False,
                                                       [sel_spec])
        self.assertEqual(traversal_spec.name, "dc_to_hf")
        self.assertEqual(traversal_spec.path, "hostFolder")
        self.assertEqual(traversal_spec.selectSet, [sel_spec])
        self.assertFalse(traversal_spec.skip)
        self.assertEqual(traversal_spec.type, "Datacenter")

    @mock.patch.object(vim_util, 'build_selection_spec')
    def test_build_recursive_traversal_spec(self, build_selection_spec_mock):
        sel_spec = mock.Mock()
        rp_to_rp_sel_spec = mock.Mock()
        rp_to_vm_sel_spec = mock.Mock()

        def build_sel_spec_side_effect(client_factory, name):
            if name == 'visitFolders':
                return sel_spec
            elif name == 'rp_to_rp':
                return rp_to_rp_sel_spec
            elif name == 'rp_to_vm':
                return rp_to_vm_sel_spec
            else:
                return None

        build_selection_spec_mock.side_effect = build_sel_spec_side_effect
        traversal_spec_dict = {'dc_to_hf': {'type': 'Datacenter',
                                            'path': 'hostFolder',
                                            'skip': False,
                                            'selectSet': [sel_spec]},
                               'dc_to_vmf': {'type': 'Datacenter',
                                             'path': 'vmFolder',
                                             'skip': False,
                                             'selectSet': [sel_spec]},
                               'h_to_vm': {'type': 'HostSystem',
                                           'path': 'vm',
                                           'skip': False,
                                           'selectSet': [sel_spec]},
                               'cr_to_h': {'type': 'ComputeResource',
                                           'path': 'host',
                                           'skip': False,
                                           'selectSet': []},
                               'cr_to_ds': {'type': 'ComputeResource',
                                            'path': 'datastore',
                                            'skip': False,
                                            'selectSet': []},
                               'cr_to_rp': {'type': 'ComputeResource',
                                            'path': 'resourcePool',
                                            'skip': False,
                                            'selectSet': [rp_to_rp_sel_spec,
                                                          rp_to_vm_sel_spec]},
                               'cr_to_rp': {'type': 'ComputeResource',
                                            'path': 'resourcePool',
                                            'skip': False,
                                            'selectSet': [rp_to_rp_sel_spec,
                                                          rp_to_vm_sel_spec]},
                               'ccr_to_h': {'type': 'ClusterComputeResource',
                                            'path': 'host',
                                            'skip': False,
                                            'selectSet': []},
                               'ccr_to_ds': {'type': 'ClusterComputeResource',
                                             'path': 'datastore',
                                             'skip': False,
                                             'selectSet': []},
                               'ccr_to_rp': {'type': 'ClusterComputeResource',
                                             'path': 'resourcePool',
                                             'skip': False,
                                             'selectSet': [rp_to_rp_sel_spec,
                                                           rp_to_vm_sel_spec]},
                               'rp_to_rp': {'type': 'ResourcePool',
                                            'path': 'resourcePool',
                                            'skip': False,
                                            'selectSet': [rp_to_rp_sel_spec,
                                                          rp_to_vm_sel_spec]},
                               'rp_to_vm': {'type': 'ResourcePool',
                                            'path': 'vm',
                                            'skip': False,
                                            'selectSet': [rp_to_rp_sel_spec,
                                                          rp_to_vm_sel_spec]},
                               }

        client_factory = mock.Mock()
        client_factory.create.side_effect = lambda ns: mock.Mock()
        trav_spec = vim_util.build_recursive_traversal_spec(client_factory)
        self.assertEqual(trav_spec.name, "visitFolders")
        self.assertEqual(trav_spec.path, "childEntity")
        self.assertFalse(trav_spec.skip)
        self.assertEqual(trav_spec.type, "Folder")

        self.assertEqual(len(trav_spec.selectSet),
                         len(traversal_spec_dict) + 1)
        for spec in trav_spec.selectSet:
            if spec.name not in traversal_spec_dict:
                self.assertEqual(spec, sel_spec)
            else:
                exp_spec = traversal_spec_dict[spec.name]
                self.assertEqual(spec.type, exp_spec['type'])
                self.assertEqual(spec.path, exp_spec['path'])
                self.assertEqual(spec.skip, exp_spec['skip'])
                self.assertEqual(spec.selectSet, exp_spec['selectSet'])

    def test_build_property_spec(self):
        client_factory = mock.Mock()
        prop_spec = vim_util.build_property_spec(client_factory)
        self.assertFalse(prop_spec.all)
        self.assertEqual(prop_spec.pathSet, ["name"])
        self.assertEqual(prop_spec.type, "VirtualMachine")

    def test_build_object_spec(self):
        client_factory = mock.Mock()
        root_folder = mock.Mock()
        specs = [mock.Mock()]
        obj_spec = vim_util.build_object_spec(client_factory,
                                              root_folder, specs)
        self.assertEqual(obj_spec.obj, root_folder)
        self.assertEqual(obj_spec.selectSet, specs)
        self.assertFalse(obj_spec.skip)

    def test_build_property_filter_spec(self):
        client_factory = mock.Mock()
        prop_specs = [mock.Mock()]
        obj_specs = [mock.Mock()]
        filter_spec = vim_util.build_property_filter_spec(client_factory,
                                                          prop_specs,
                                                          obj_specs)
        self.assertEqual(filter_spec.objectSet, obj_specs)
        self.assertEqual(filter_spec.propSet, prop_specs)

    @mock.patch(
        'openstack.common.vmware.vim_util.build_recursive_traversal_spec')
    def test_get_objects(self, build_recursive_traversal_spec):
        vim = mock.Mock()
        trav_spec = mock.Mock()
        build_recursive_traversal_spec.return_value = trav_spec
        max_objects = 10
        _type = "VirtualMachine"

        def vim_RetrievePropertiesEx_side_effect(pc, specSet, options):
            self.assertTrue(pc is vim.service_content.propertyCollector)
            self.assertEqual(options.maxObjects, max_objects)

            self.assertEqual(len(specSet), 1)
            property_filter_spec = specSet[0]

            propSet = property_filter_spec.propSet
            self.assertEqual(len(propSet), 1)
            prop_spec = propSet[0]
            self.assertFalse(prop_spec.all)
            self.assertEqual(prop_spec.pathSet, ["name"])
            self.assertEqual(prop_spec.type, _type)

            objSet = property_filter_spec.objectSet
            self.assertEqual(len(objSet), 1)
            obj_spec = objSet[0]
            self.assertTrue(obj_spec.obj is vim.service_content.rootFolder)
            self.assertEqual(obj_spec.selectSet, [trav_spec])
            self.assertFalse(obj_spec.skip)

        vim.RetrievePropertiesEx.side_effect = \
            vim_RetrievePropertiesEx_side_effect
        vim_util.get_objects(vim, _type, max_objects)
        self.assertEqual(vim.RetrievePropertiesEx.call_count, 1)

    def test_get_object_properties_with_empty_moref(self):
        vim = mock.Mock()
        ret = vim_util.get_object_properties(vim, None, None)
        self.assertEqual(ret, None)

    @mock.patch('openstack.common.vmware.vim_util.cancel_retrieval')
    def test_get_object_properties(self, cancel_retrieval):
        vim = mock.Mock()
        moref = mock.Mock()
        moref.type = "VirtualMachine"
        retrieve_result = mock.Mock()

        def vim_RetrievePropertiesEx_side_effect(pc, specSet, options):
            self.assertTrue(pc is vim.service_content.propertyCollector)
            self.assertEqual(options.maxObjects, 1)

            self.assertEqual(len(specSet), 1)
            property_filter_spec = specSet[0]

            propSet = property_filter_spec.propSet
            self.assertEqual(len(propSet), 1)
            prop_spec = propSet[0]
            self.assertTrue(prop_spec.all)
            self.assertEqual(prop_spec.pathSet, ['name'])
            self.assertEqual(prop_spec.type, moref.type)

            objSet = property_filter_spec.objectSet
            self.assertEqual(len(objSet), 1)
            obj_spec = objSet[0]
            self.assertEqual(obj_spec.obj, moref)
            self.assertEqual(obj_spec.selectSet, [])
            self.assertFalse(obj_spec.skip)

            return retrieve_result

        vim.RetrievePropertiesEx.side_effect = \
            vim_RetrievePropertiesEx_side_effect

        res = vim_util.get_object_properties(vim, moref, None)
        self.assertEqual(vim.RetrievePropertiesEx.call_count, 1)
        self.assertTrue(res is retrieve_result.objects)
        cancel_retrieval.assert_called_once_with(vim, retrieve_result)

    def test_get_token(self):
        retrieve_result = object()
        self.assertFalse(vim_util._get_token(retrieve_result))

    @mock.patch('openstack.common.vmware.vim_util._get_token')
    def test_cancel_retrieval(self, get_token):
        token = mock.Mock()
        get_token.return_value = token
        vim = mock.Mock()
        retrieve_result = mock.Mock()
        vim_util.cancel_retrieval(vim, retrieve_result)
        get_token.assert_called_once_with(retrieve_result)
        vim.CancelRetrievePropertiesEx.assert_called_once_with(
            vim.service_content.propertyCollector, token=token)

    @mock.patch('openstack.common.vmware.vim_util._get_token')
    def test_continue_retrieval(self, get_token):
        token = mock.Mock()
        get_token.return_value = token
        vim = mock.Mock()
        retrieve_result = mock.Mock()
        vim_util.continue_retrieval(vim, retrieve_result)
        get_token.assert_called_once_with(retrieve_result)
        vim.ContinueRetrievePropertiesEx.assert_called_once_with(
            vim.service_content.propertyCollector, token=token)

    @mock.patch('openstack.common.vmware.vim_util.get_object_properties')
    def test_get_object_property(self, get_object_properties):
        prop = mock.Mock()
        prop.val = "ubuntu-12.04"
        properties = mock.Mock()
        properties.propSet = [prop]
        properties_list = [properties]
        get_object_properties.return_value = properties_list
        vim = mock.Mock()
        moref = mock.Mock()
        property_name = 'name'
        val = vim_util.get_object_property(vim, moref, property_name)
        self.assertEqual(val, prop.val)
        get_object_properties.assert_called_once_with(
            vim, moref, [property_name])
