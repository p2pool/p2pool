from __future__ import absolute_import

import argparse
import sys


class FixedArgumentParser(argparse.ArgumentParser):
    '''
    fixes argparse's handling of empty string arguments
and changes @filename behaviour to accept multiple arguments on each line
    '''
    
    def _read_args_from_files(self, arg_strings):
        # expand arguments referencing files
        new_arg_strings = []
        for arg_string in arg_strings:
            
            # for regular arguments, just add them back into the list
            if not arg_string or arg_string[0] not in self.fromfile_prefix_chars:
                new_arg_strings.append(arg_string)
            
            # replace arguments referencing files with the file content
            else:
                try:
                    args_file = open(arg_string[1:])
                    try:
                        arg_strings = []
                        for arg_line in args_file.read().splitlines():
                            for arg in self.convert_arg_line_to_args(arg_line):
                                arg_strings.append(arg)
                        arg_strings = self._read_args_from_files(arg_strings)
                        new_arg_strings.extend(arg_strings)
                    finally:
                        args_file.close()
                except IOError:
                    err = sys.exc_info()[1]
                    self.error(str(err))
        
        # return the modified argument list
        return new_arg_strings
    
    def convert_arg_line_to_args(self, arg_line):
        return [arg for arg in arg_line.split() if arg.strip()]
