#!/usr/bin/env python
# encoding: utf-8
#
# Description: Multiple Analysis Generic Unifier and Interpreter aka Magui
#              This program processes several snapshoot/sosreport files
#              and processes citellus output for combined issues via plugins
#              that search for specific plugin and data
#
# Copyright (C) 2017  Pablo Iranzo Gómez (Pablo.Iranzo@redhat.com)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


from __future__ import print_function

import argparse
import datetime
import gettext
import json
import logging
import os.path
import pprint
import imp

try:
    # Python 3
    from . import shell as citellus
except ValueError:
    # Python 2
    import shell as citellus

LOG = logging.getLogger('magui')

# Where are we?
maguidir = os.path.abspath(os.path.dirname(__file__))
localedir = os.path.join(maguidir, 'locale')

global PluginsFolder
PluginsFolder = os.path.join(maguidir, "magplug")

global plugins
plugins = []
global plugtriggers
plugtriggers = {}

trad = gettext.translation('citellus', localedir, fallback=True)

try:
    _ = trad.ugettext
except AttributeError:
    _ = trad.gettext


def show_logo():
    """
    Prints Magui Logo
    :return:
    """

    logo = "    _    ", \
           "  _( )_  Magui:", \
           " (_(ø)_) ", \
           "  /(_)   Multiple Analisis Generic Unifier and Interpreter", \
           " \|      ", \
           "  |/     ", \
           ""
    print("\n".join(logo))


def parse_args():
    """
    Parses arguments on commandline
    :return: parsed arguments
    """
    description = _('Processes several generic archives/sosreports scripts in a uniform way, to interpret status that depend on several systems data')

    # Option parsing
    p = argparse.ArgumentParser("magui.py [arguments]", description=description)
    p.add_argument('-d', "--loglevel",
                   help=_("Set log level"),
                   default="info",
                   type=lambda x: x.upper(),
                   choices=["INFO", "DEBUG", "WARNING", "ERROR", "CRITICAL"])
    p.add_argument("--list-plugins",
                   action="store_true",
                   help=_("Print a list of discovered Magui plugins and exit"))
    p.add_argument("--description",
                   action="store_true",
                   help=_("With list-plugins, also outputs plugin description"))
    p.add_argument('-p', "--pluginpath", dest="pluginpath",
                   help=_("Set path for Citellus plugin location if not default"),
                   action='append')
    p.add_argument('-m', "--mpath", dest="mpath",
                   help=_("Set path for Magui plugin location if not default"),
                   action='append')
    p.add_argument("--output", "-o",
                   metavar="FILENAME",
                   help=_("Write results to JSON file FILENAME"))
    p.add_argument("--run", "-r",
                   action='store_true',
                   help=_("Force run of citellus instead of reading existing 'citellus.json'"))

    g = p.add_argument_group('Filtering options')
    g.add_argument("-q", "--quiet",
                   help=_("Enable quiet mode"),
                   action='store_true')
    g.add_argument("-i", "--include",
                   metavar='SUBSTRING',
                   help=_("Only include plugins that contain substring"),
                   default=[],
                   action='append')
    g.add_argument("-x", "--exclude",
                   metavar='SUBSTRING',
                   help=_("Exclude plugins that contain substring"),
                   default=[],
                   action='append')

    g.add_argument("-mf", "--mfilter", dest="mfilter",
                   help=_("Only include Magui plugins that contains in full path that substring"),
                   default=[],
                   action='append')

    p.add_argument('sosreports', nargs='*')

    return p.parse_args()


def commonpath(folders):
    """
    Checks the minimum common path in provided paths
    :param folders: path array for folder
    :return: string: common path
    """

    code = ""
    if folders:
        try:
            # Python 3.x
            code = os.path.commonpath(folders)
        except AttributeError:
            # Python 2.x
            code = os.path.commonprefix(folders).rsplit('/', 1)[0]

    return code


def getPlugins(options):
    """
    Gets list of Plugins in the magplug folder
    :return: list of Plugins available
    """

    Plugins = []
    possiblePlugins = citellus.findplugins(folders=[PluginsFolder], executables=False, exclude=['__init__.py', 'pyc'], include=options.mfilter, fileextension='.py')
    for i in possiblePlugins:
        module = os.path.splitext(os.path.basename(i['plugin']))[0]
        modpath = os.path.dirname(i['plugin'])
        try:
            info = imp.find_module(module, [modpath])
        except:
            info = False
        if i['plugin'] and info:
            Plugins.append({"name": module, "info": info})

    return Plugins


def loadPlugin(Plugin):
    """
    Loads selected Plugin
    :param Plugin: Plugin to load
    :return: loader for Plugin
    """
    return imp.load_module(Plugin["name"], *Plugin["info"])


def initPlugins(options):
    """
    Initializes Plugins
    :return: list of Plugin modules initialized
    """

    plugs = []
    plugtriggers = {}
    for i in getPlugins(options):
        newplug = loadPlugin(i)
        plugs.append(newplug)
        triggers = []
        for each in newplug.init():
            triggers.append(each)
        plugtriggers[i["name"]] = triggers
    return plugs, plugtriggers


def callcitellus(path=False, plugins=False, forcerun=False):
    """
    Do actual execution of citellus against data
    :param path: sosreport path
    :param plugins: plugins enabled as provided to citellus
    :return: dict with results
    """

    filename = os.path.join(path, 'citellus.json')
    if os.access(filename, os.R_OK) and not forcerun:
        LOG.debug("Reading Existing citellus analysis from disk for %s" % path)
        oldresults = json.load(open(filename, 'r'))['results']
        # Need to apply filters as by default the stored file will have everything
        results = []

        for result in oldresults:
            for plugin in plugins:
                if result['plugin'] == plugin['plugin']:
                    # We have a match with the plugin defined and the ones we expect, so append results
                    results.append(result)

    else:
        LOG.debug("Running citellus analysis for %s" % path)
        # Call citellus and format data returned
        results = citellus.docitellus(path=path, plugins=plugins)

    # Process plugin output from multiple plugins
    new_dict = {}
    for item in results:
        name = item['plugin']
        new_dict[name] = item
    return new_dict


def domagui(sosreports, citellusplugins, options=False):
    """
    Do actual execution against sosreports
    :return: dict of results
    """

    # Check if we've been provided options
    if options:
        forcerun = options.run
    else:
        forcerun = False

    # Grab data from citellus for the sosreports provided
    results = {}

    for sosreport in sosreports:
        results[sosreport] = callcitellus(path=sosreport, plugins=citellusplugins, forcerun=forcerun)

    # Sanity check in case we do need to force run because of inconsistencies between saved data
    if not forcerun:
        # Prefill all plugins
        plugins = []
        for sosreport in sosreports:
            for plugin in results[sosreport]:
                plugins.append(plugin)

        plugins = sorted(set(plugins))

        rerun = False
        # Check all sosreports for data for all plugins
        for sosreport in sosreports:
            try:
                results[sosreport][plugin]['result']
            except:
                LOG.debug("Forcing rerun of citellus for %s because of missing %s" % (sosreport, plugin))
                rerun = True

            if rerun:
                # Sosreport contains non uniform data, rerun
                results[sosreport] = callcitellus(path=sosreport, plugins=citellusplugins, forcerun=True)

    # Precreate multidimensional array
    grouped = {}
    for sosreport in sosreports:
        plugins = []
        for plugin in results[sosreport]:
            plugins.append(plugin)
            grouped[plugin] = {}
            grouped[plugin]['sosreport'] = {}

    # Fill the data
    for sosreport in sosreports:
        for plugin in results[sosreport]:
            grouped[plugin]['sosreport'][sosreport] = results[sosreport][plugin]['result']
            for element in results[sosreport][plugin]:
                # Some of the elements are not useful as they are sosreport specific, so we do skip them completely
                # In this approach we don't need to update this code each time the plugin exports new metadata
                if element not in ['time', 'result']:
                    grouped[plugin][element] = results[sosreport][plugin][element]

    # We've now a matrix of grouped[plugin][sosreport] and then [text] [out] [err] [rc]
    return grouped


def write_results(results, filename):
    """
    Writes result
    :param results: Data to write
    :param filename: File to use
    :return:
    """
    data = {
        'metadata': {
            'when': datetime.datetime.utcnow().isoformat(),
        },
        'results': results,
    }

    with open(filename, 'w') as fd:
        json.dump(data, fd, indent=2)


def maguiformat(data):
    """
    Formats the data from Magui for printing
    :param data: Results from domagui
    :return: dict with results for printing
    """
    toprint = {}

    plugins = []
    for plugin in data:
        plugins.append(plugin)

    # Calculate common path for later filtering for output print
    cp = commonpath(plugins)

    for plugin in data:
        pplug = 0
        for host in data[plugin]['sosreport']:
            if data[plugin]['sosreport'][host]['rc'] != citellus.RC_OKAY and data[plugin]['sosreport'][host]['rc'] != citellus.RC_SKIPPED:
                pplug = 1
        if pplug == 1:
            newplugin = plugin.replace(cp, '')
            toprint[newplugin] = {}
            toprint[newplugin]['sosreport'] = {}
            for host in data[plugin]:
                toprint[newplugin]['sosreport'][host] = {}
                toprint[newplugin]['sosreport'][host] = data[plugin][host]
    return toprint


def main():
    """
    Main code stub
    """
    options = parse_args()

    # Configure logging
    logging.basicConfig(level=options.loglevel)

    if not options.quiet:
        show_logo()

    # Each argument in sosreport is a sosreport

    magplugs, magtriggers = initPlugins(options)

    if options.list_plugins:
        for plugin in magplugs:
            print("-", plugin.__name__.split(".")[-1])
            if options.description:
                desc = plugin.help()
                if desc:
                    print(citellus.indent(text=desc, amount=4))
        return

    # Prefill enabled citellus plugins from args
    if not citellus.extensions:
        extensions, exttriggers = citellus.initExtensions()
    else:
        extensions = citellus.extensions

    citellusplugins = []
    for extension in extensions:
        citellusplugins.extend(extension.listplugins(options))

    # By default, flatten plugin list for all extensions
    newplugins = []
    for each in citellusplugins:
        newplugins.extend(each)

    citellusplugins = newplugins

    # Grab the data
    grouped = domagui(sosreports=options.sosreports, citellusplugins=citellusplugins, options=options)

    # Run Magui plugins
    results = []
    for plugin in magplugs:
        results.append({'plugin': plugin.__name__.split(".")[-1], 'results': plugin.run(data=grouped, quiet=options.quiet)})

    if options.output:
        write_results(results=results, filename=options.output)

    pprint.pprint(results, width=1)


if __name__ == "__main__":
    main()
