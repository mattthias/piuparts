import unittest
from piupartslib import packagesdb
import StringIO

example_packages = 'Package: testdata\n\
Version: 4.7.11-1\n\
Maintainer: Unsung Hero <u.hero@example.com>\n\
Description: test data to imitate a Packages file\n\
 This is the multi line description of test data.\n\
 It is yadda yadda foo bar stuff\n\
 .\
 Just more yadda\n'


class PackagesdbTest(unittest.TestCase):

    def setUp(self):
        self._packages_stream = StringIO.StringIO(example_packages)
        self._empty_stream = StringIO.StringIO('')

    def test_rfc822_like_header_parse_with_empty_input(self):
        header = packagesdb.rfc822_like_header_parse(self._empty_stream)
        self.assertEqual(header, [])

    def test_rfc822_like_header_parse_with_input(self):
        '''
        Test if the function returns a list with one key-value pair per
        element.
        '''
        header = packagesdb.rfc822_like_header_parse(self._packages_stream)
        self.assertIn('Package: testdata\n', header)
        self.assertIn('Version: 4.7.11-1\n', header)
        self.assertIn('Maintainer: Unsung Hero <u.hero@example.com>\n', header)
        self.assertEqual(len(header), 4)
