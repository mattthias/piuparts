#!/usr/bin/python
#
# Copyright 2005 Lars Wirzenius (liw@iki.fi)
# 
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.
# 
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General
# Public License for more details.
# 
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA


"""Distributed piuparts processing, master program

Lars Wirzenius <liw@iki.fi>
"""


import sys
import logging
import urllib
import ConfigParser
import os
import tempfile


import piupartslib


CONFIG_FILE = "piuparts-master.conf"


def setup_logging(log_level, log_file_name):
    logger = logging.getLogger()
    logger.setLevel(log_level)

    if log_file_name:
        handler = logging.FileHandler(log_file_name)
    else:
        handler = logging.StreamHandler(sys.stderr)
    logger.addHandler(handler)


class Config(piupartslib.conf.Config):

    def __init__(self, section="master"):
        piupartslib.conf.Config.__init__(self, section,
            {
                "log-file": None,
                "packages-url": None,
            },
            ["packages-url"])


class CommandSyntaxError(Exception):

    def __init__(self, msg):
        self.args = msg


class ProtocolError(Exception):

    def __init__(self):
        self.args = "EOF, missing space in long part, or other protocol error"


class Protocol:

    def __init__(self, input, output):
        self._input = input
        self._output = output

    def _readline(self):
        line = self._input.readline()
        logging.debug(">> " + line.rstrip())
        return line
        
    def _writeline(self, line):
        logging.debug("<< " + line)
        self._output.write(line + "\n")
        self._output.flush()

    def _short_response(self, *words):
        self._writeline(" ".join(words))

    def _read_long_part(self):
        lines = []
        while True:
            line = self._readline()
            if not line:
                raise ProtocolError()
            if line == ".\n":
                break
            if line[0] != " ":
                raise ProtocolError()
            lines.append(line[1:])
        return "".join(lines)


class Master(Protocol):

    _failed_states = (
        "failed-testing",
        "fix-not-yet-tested",
    )
    _passed_states = (
        "successfully-tested",
    )

    def __init__(self, input, output, packages_file, section=None):
        Protocol.__init__(self, input, output)
        self._commands = {
            "reserve": self._reserve,
            "unreserve": self._unreserve,
            "pass": self._pass,
            "fail": self._fail,
            "untestable": self._untestable,
        }
        self._db = piupartslib.packagesdb.PackagesDB(prefix=section)
        self._db.create_subdirs()
        self._db.read_packages_file(packages_file)
        self._writeline("hello")

    def do_transaction(self):
        line = self._readline()
        if line:
            parts = line.split()
            if len(parts) > 0:
                command = parts[0]
                args = parts[1:]
                self._commands[command](command, args)
            return True
        else:
            return False

    def _check_args(self, count, command, args):
        if len(args) != count:
            raise CommandSyntaxError("Need exactly %d args: %s %s" %
                                     (count, command, " ".join(args)))

    def _reserve(self, command, args):
        self._check_args(0, command, args)
        package = self._db.reserve_package()
        if package is None:
            self._short_response("error")
        else:
            self._short_response("ok", 
                                 package["Package"], 
                                 package["Version"])

    def _unreserve(self, command, args):
        self._check_args(2, command, args)
        self._db.unreserve_package(args[0], args[1])
        self._short_response("ok")

    def _pass(self, command, args):
        self._check_args(2, command, args)
        log = self._read_long_part()
        self._db.pass_package(args[0], args[1], log)
        self._short_response("ok")

    def _fail(self, command, args):
        self._check_args(2, command, args)
        log = self._read_long_part()
        self._db.fail_package(args[0], args[1], log)
        self._short_response("ok")

    def _untestable(self, command, args):
        self._check_args(2, command, args)
        log = self._read_long_part()
        self._db.make_package_untestable(args[0], args[1], log)
        self._short_response("ok")

    def count_packages_in_states(self, states):
        count = 0
        for state in states:
            count += len(self._db.get_packages_in_state(state))
        return count

    def rename_if_newer_else_delete(self, orig, new):
        ok = True
        if os.path.exists(orig):
            st_orig = os.stat(orig)
            st_new = os.stat(new)
            ok = st_orig.st_mtime < st_new.st_mtime
        if ok:
            os.rename(new, orig)
        else:
            os.remove(new)

    def write_counts_summary(self):
        fd, name = tempfile.mkstemp(prefix="counts.txt.", dir=".")
        os.close(fd)
        os.chmod(name, 0644)

        failed = self.count_packages_in_states(self._failed_states)
        passed = self.count_packages_in_states(self._passed_states)

        f = file(name, "w")
        f.write("Fail: %d\n" % failed)
        f.write("Pass: %d\n" % passed)
        f.close()
        self.rename_if_newer_else_delete("counts.txt", name)

    def find_log(self, package):
        n = self._db._logdb._log_name(package["Package"], package["Version"])
        for dirname in self._db._all:
            nn = os.path.join(dirname, n)
            if os.path.exists(nn):
                return nn
        return None

    def write_packages_summary(self):
        fd, name = tempfile.mkstemp(prefix="packages.txt.", dir=".")
        os.close(fd)
        os.chmod(name, 0644)

        f = file(name, "w")
        for pkgname in self._db._packages:
            state = self._db.state_by_name(pkgname)
            logname = self.find_log(self._db._packages[pkgname]) or ""
            f.write("%s %s %s\n" % (pkgname, state, logname))
        f.close()

        self.rename_if_newer_else_delete("packages.txt", name)

    def write_summaries(self):
        self.write_counts_summary()
        self.write_packages_summary()


def main():
    # For supporting multiple architectures and suites, we take a command-line
    # argument referring to a section in the master configuration file.  For
    # backwards compatibility, if no argument is given, the "master" section is
    # assumed.
    if len(sys.argv) == 2:
        section = sys.argv[1]
        config = Config(section=section)
    else:
        section = None
        config = Config()
    config.read(CONFIG_FILE)
    
    setup_logging(logging.DEBUG, config["log-file"])
    
    logging.info("Fetching %s" % config["packages-url"])
    packages_file = piupartslib.open_packages_url(config["packages-url"])
    m = Master(sys.stdin, sys.stdout, packages_file, section=section)
    packages_file.close()
    while m.do_transaction():
        pass
    m.write_summaries()


if __name__ == "__main__":
    main()