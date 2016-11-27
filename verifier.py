#!/usr/local/bin/python3
# -*- coding: utf-8 -*-

# The MIT License (MIT)
# Copyright (c) 2016 Nick Kocharhook
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all 
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE 
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE 
# SOFTWARE.

import csv
import os
import re
import argparse
from difflib import SequenceMatcher

def main():
	args = parseArguments()

	for path in args.paths:
		verifier = Verifier(path)

		if verifier.ready and "matrix" not in verifier.filename:
			verifier.verify()


def parseArguments():
	parser = argparse.ArgumentParser(description='Verify openelections CSV files')
	parser.add_argument('paths', metavar='N', type=str, nargs='+',
					   help='path to a CSV file')

	return parser.parse_args()


class Verifier(object):
	validColumns = frozenset(['county', 'precinct', 'office', 'district', 'party', 'candidate', 'votes', 'notes'])
	requiredColumns = frozenset(['county', 'precinct', 'office', 'district', 'party', 'candidate', 'votes'])
	validOffices = frozenset(['President', 'U.S. Senate', 'U.S. House', 'Governor', 'State Senate', 'State House', 'Attorney General', 'Secretary of State', 'State Treasurer'])
	officesWithDistricts = frozenset(['U.S. House', 'State Senate', 'State House'])
	pseudocandidates = frozenset(['Write-in', 'Under Votes', 'Over Votes', 'Total'])
	normalizedPseudocandidates = frozenset(['writein', 'undervotes', 'overvotes', 'total'])

	# Return the appropriate subclass based on the path
	def __new__(cls, path):
		if cls is Verifier:
			filename = os.path.basename(path)

			if "general" in filename:
				if "precinct" in filename:
					return super(Verifier, cls).__new__(GeneralPrecinctVerifier)
				else:
					return super(Verifier, cls).__new__(GeneralVerifier)
			elif "primary" in filename:
				if "precinct" in filename:
					return super(Verifier, cls).__new__(PrimaryPrecinctVerifier)
				else:
					return super(Verifier, cls).__new__(PrimaryVerifier)
			elif "special" in filename and "precinct" in filename:
				return super(Verifier, cls).__new__(SpecialPrecinctVerifier)

		else:
			return super(Verifier, cls).__new__(cls, path)

	def __init__(self, path):
		self.path = path
		self.columns = []
		self.reader = None
		self.ready = False

		self.countyRE = re.compile("\d{8}__[a-z]{2}_")

		try:
			self.pathSanityCheck(path)

			self.filename = os.path.basename(path)
			self.filenameState, self.filenameCounty = self.deriveStateCountyFromFilename(self.filename)

			self.ready = True
		except Exception as e:
			print("ERROR: {}".format(e))

	def verify(self):
		self.parseFileAtPath(self.path)

	def pathSanityCheck(self, path):
		if not os.path.exists(path) or not os.path.isfile(path):
			raise FileNotFoundError("Can't find file at path %s" % path)

		if not os.path.splitext(path)[1] == ".csv":
			raise ValueError("Filename does not end in .csv: %s" % path)

		print("==> {}".format(path))

	def deriveStateCountyFromFilename(self, filename):
		components = filename.split("__")

		if len(components) == 5:
			return (components[1], components[3].replace("_", " ").title())

		return ""

	def parseFileAtPath(self, path):
		with open(path, 'rU') as csvfile:
			self.reader = csv.DictReader(csvfile)
			
			if self.verifyColumns(self.reader.fieldnames):
				for row in self.reader:
					self.verifyCounty(row)
					self.verifyOffice(row)
					self.verifyDistrict(row)
					self.verifyCandidate(row)
					self.verifyParty(row)

	def verifyColumns(self, columns):
		invalidColumns = set(columns) - Verifier.validColumns
		missingColumns = Verifier.requiredColumns - set(columns)

		if invalidColumns:
			self.printError("Invalid columns: {}".format(invalidColumns))

		if missingColumns:
			self.printError("Missing columns: {}".format(missingColumns))
			return False

		return True

	def verifyCounty(self, row):
		normalisedCounty = row['county'].title()

		if not normalisedCounty == self.filenameCounty:
			self.printError("County doesn't match filename", row)

		if not row['county'] == normalisedCounty:
			self.printError("Use title case for the county", row)

	def verifyOffice(self, row):
		if not row['office'] in Verifier.validOffices:
			self.self.printError("Invalid office: {}".format(row['office']), row)

	def verifyDistrict(self, row):
		if row['office'] in Verifier.officesWithDistricts:
			if not row['district']:
				self.printError("Office '{}' requires a district".format(row['office']), row)
			elif row['district'].lower() == 'x':
				if self.filenameState == 'ms':
					pass # This is legit in some MS precincts
				else:
					self.printError("District must be an integer", row)
			elif not self.verifyInteger(row['district']):
				self.printError("District must be an integer", row)

	def verifyCandidate(self, row):
		charsRE = re.compile('[^A-Za-z]+', re.UNICODE)
		candidate = row['candidate']
		normalizedCandidate = charsRE.sub('', candidate).lower()

		if candidate not in Verifier.pseudocandidates:
			if normalizedCandidate in Verifier.normalizedPseudocandidates:
				self.printError("Misspelled pseudocandidate: '{}'".format(candidate), row)
			else:
				# Compare the normalized strings to determine if they match
				for npc in Verifier.normalizedPseudocandidates:
					s = SequenceMatcher(None, normalizedCandidate, npc)
					match = s.find_longest_match(0, len(normalizedCandidate), 0, len(npc))

					if match.size > 4:
						self.printError("Misspelled pseudocandidate: '{}'".format(candidate), row)
						break

	def verifyParty(self, row):
		if row['candidate'] not in Verifier.pseudocandidates and not row['party']:
			self.printError("Party missing", row)

	def verifyInteger(self, numberStr):
		try:
			integer = int(numberStr)
		except ValueError as e:
			return False

		return True

	def printError(self, text, row=[]):
		print("ERROR: " + text)

		if row:
			print(row)


class GeneralPrecinctVerifier(Verifier):
	pass

class PrimaryPrecinctVerifier(Verifier):
	def verifyParty(self, row):
		if not row['party']:
			self.printError("Primary results must include a party for every row", row)

class SpecialPrecinctVerifier(Verifier):
	pass


class PrimaryVerifier(Verifier):
	pass

class GeneralVerifier(Verifier):
	pass


# Default function is main()
if __name__ == '__main__':
	main()