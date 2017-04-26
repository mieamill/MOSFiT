# -*- encoding: utf-8 -*-
"""Defines the `Printer` class."""
from __future__ import print_function, unicode_literals

import datetime
import json
import os
import re
import sys
from builtins import input, str
from textwrap import fill

import numpy as np

from .utils import calculate_WAIC, congrid, is_integer, open_atomic, pretty_num

if sys.version_info[:2] < (3, 3):
    old_print = print  # noqa

    def print(*args, **kwargs):
        """Replacement for print function in Python 2.x."""
        flush = kwargs.pop('flush', False)
        old_print(*args, **kwargs)
        file = kwargs.get('file', sys.stdout)
        if flush and file is not None:
            file.flush()


class Printer(object):
    """Print class for MOSFiT."""

    class ansi(object):
        """Special formatting characters."""

        BLUE = '\033[0;94m'
        BOLD = '\033[0;1m'
        CYAN = '\033[0;96m'
        END = '\033[0m'
        GREEN = '\033[0;92m'
        HEADER = '\033[0;95m'
        MAGENTA = '\033[1;35m'
        ORANGE = '\033[38;5;214m'
        RED = '\033[0;91m'
        UNDERLINE = '\033[4m'
        YELLOW = '\033[0;93m'

        codes = {
            '!b': BLUE,
            '!c': CYAN,
            '!e': END,
            '!g': GREEN,
            '!m': MAGENTA,
            '!o': ORANGE,
            '!r': RED,
            '!u': UNDERLINE,
            '!y': YELLOW
        }

    def __init__(self, pool=None, wrap_length=100, quiet=False, fitter=None,
                 language='en'):
        """Initialize printer, setting wrap length."""
        self._wrap_length = wrap_length
        self._quiet = quiet
        self._pool = pool
        self._fitter = fitter
        self._language = language

        self.set_strings()

    def set_strings(self):
        """Set pre-defined list of strings."""
        dir_path = os.path.dirname(os.path.realpath(__file__))
        with open(os.path.join(dir_path, 'strings.json')) as f:
            strings = json.load(f)
        if self._language == 'en':
            self._strings = strings
            return
        lsf = os.path.join(dir_path, 'strings-' + self._language + '.json')
        if os.path.isfile(lsf):
            with open(lsf) as f:
                self._strings = json.load(f)
            if set(self._strings.keys()) == set(strings):
                return

        try:
            from googletrans import Translator  # noqa
        except Exception:
            self.prt(
                'The `--language` option requires the `Googletrans` package. '
                'Please install with `pip install googletrans`.', wrapped=True)
            self._strings = strings
            pass
        else:
            self.prt(self.translate(
                'Building strings for `{}`, please wait...'
                .format(self._language)), wrapped=True)
            self._strings = {}
            for key in strings:
                self._strings[key] = self.translate(strings[key])
            with open_atomic(lsf, 'w') as f:
                json.dump(self._strings, f)

    def set_language(self, language):
        """Set language."""
        self._language = language

    def colorify(self, text):
        """Add colors to text."""
        output = text
        for code in self.ansi.codes:
            output = output.replace(code, self.ansi.codes[code])
        return output

    def _lines(
        self, text, colorify=False, center=False, width=None,
        warning=False, error=False, prefix=True, color='', inline=False,
            wrap_length=None, wrapped=False, master_only=True):
        """Generate lines for output."""
        if self._quiet:
            return []
        if master_only and self._pool and not self._pool.is_master():
            return []
        if warning:
            if prefix:
                text = '!y' + self._strings['warning'] + ': ' + text + '!e'
        if error:
            if prefix:
                text = '!r' + self._strings['error'] + ': ' + text + '!e'
        if color:
            text = color + text + '!e'
        tspl = (text + '\n').splitlines()
        if wrapped:
            if not wrap_length or not is_integer(wrap_length):
                wrap_length = self._wrap_length
            ntspl = []
            for line in tspl:
                ntspl.extend(fill(line, wrap_length).splitlines())
            tspl = ntspl
        return tspl

    def prt(self, text, **kwargs):
        """Print text without modification."""
        warning = kwargs.get('warning', False)
        error = kwargs.get('error', False)
        color = kwargs.get('color', '')
        inline = kwargs.get('inline', False)
        center = kwargs.get('center', False)
        width = kwargs.get('width', None)
        colorify = kwargs.get('colorify', False)
        tspl = self._lines(text, **kwargs)
        if warning or error or color:
            colorify = True
        if inline and self._fitter is not None:
            inline = not self._fitter._test
        if inline:
            for line in tspl:
                sys.stdout.write("\033[F")
                sys.stdout.write("\033[K")
        for ri, line in enumerate(tspl):
            rline = line
            if colorify:
                rline = self.colorify(rline)
            if center:
                tlen = len(repr(rline)) - len(line) - line.count('!')
                rline = rline.center(width + tlen)
            try:
                print(rline, flush=True)
            except UnicodeEncodeError:
                print(rline.encode('ascii', 'replace').decode(), flush=True)

    def string(self, text, **kwargs):
        """Return message string."""
        center = kwargs.get('center', False)
        width = kwargs.get('width', None)
        tspl = self._lines(text, **kwargs)
        lines = []
        for ri, line in enumerate(tspl):
            rline = line
            if center:
                tlen = len(repr(rline)) - len(line) - line.count('!')
                rline = rline.center(width + tlen)
            lines.append(rline)
        return '\n'.join(lines)

    def message(self, name, reps=[], wrapped=True, inline=False,
                warning=False, error=False, prefix=True, center=False,
                colorify=False, width=None):
        """Print a message from a dictionary of strings."""
        if name in self._strings:
            text = self._strings[name]
        else:
            text = '< Message not found [' + ''.join(
                ['{} ' for x in range(len(reps))]).strip() + '] >'
        text = text.format(*reps)
        self.prt(
            text, center=center, colorify=colorify, width=width, prefix=prefix,
            inline=inline, wrapped=wrapped, warning=warning, error=error)

    def prompt(self, text, wrap_length=None, kind='bool',
               none_string='None of the above.',
               options=None, translate=True, message=True):
        """Prompt the user for input and return a value based on response."""
        if wrap_length and is_integer(wrap_length):
            wl = wrap_length
        else:
            wl = self._wrap_length

        if kind == 'bool':
            choices = ' (y/[n])'
        elif kind == 'select':
            selpad = ''.join([' ' for x in str(len(options))])
            choices = '\n' + '\n'.join([
                ' ' + str(i + 1) + '. ' + selpad[len(str(i + 1)) - 1:] +
                options[i] for i in range(len(options))
            ] + [
                '[n].' + selpad + none_string + '\n' +
                'Enter selection (' + ('1-' if len(options) > 1 else '') + str(
                    len(options)) + '/[n]):'
            ])
        elif kind == 'string':
            choices = ''
        else:
            raise ValueError('Unknown prompt kind.')

        if message:
            text = self.string(text, wrap_length=wrap_length)
        textchoices = text + choices
        if translate:
            textchoices = self.translate(textchoices)
        prompt_txt = (textchoices).split('\n')
        for txt in prompt_txt[:-1]:
            ptxt = fill(txt, wl, replace_whitespace=False)
            self.prt(ptxt)

        user_input = input(
            fill(
                prompt_txt[-1], wl, replace_whitespace=False) + " ")
        if kind == 'bool':
            return user_input in ["Y", "y", "Yes", "yes"]
        elif kind == 'select':
            if (is_integer(user_input) and
                    int(user_input) in list(range(1, len(options) + 1))):
                return options[int(user_input) - 1]
            return False
        elif kind == 'string':
            return user_input

    def status(self,
               desc='',
               scores='',
               accepts='',
               progress='',
               acor=None,
               psrf=None,
               fracking=False,
               messages=[],
               kmat=None,
               make_space=False):
        """Print status message showing state of fitting process."""
        if self._quiet:
            return

        fitter = self._fitter
        outarr = [fitter._event_name]
        if desc:
            if desc == 'burning':
                descstr = '!o' + self._strings.get(
                    desc, '?') + '!e'
            else:
                descstr = self._strings.get(desc, '?')
            outarr.append(descstr)
        if isinstance(scores, list):
            scorestring = self._strings[
                'fracking_scores'] if fracking else self._strings[
                    'score_ranges']
            scorestring += ': [ ' + ', '.join([
                '...'.join([
                    pretty_num(min(x))
                    if not np.isnan(min(x)) and np.isfinite(min(x))
                    else 'NaN',
                    pretty_num(max(x))
                    if not np.isnan(max(x)) and np.isfinite(max(x))
                    else 'NaN']) if len(x) > 1 else pretty_num(x[0])
                for x in scores
            ]) + ' ]'
            outarr.append(scorestring)
            if not fracking:
                scorestring = 'WAIC: ' + pretty_num(calculate_WAIC(scores))
                outarr.append(scorestring)
        if isinstance(accepts, list):
            scorestring = self._strings['moves_accepted'] + ': [ '
            scorestring += ', '.join([
                ('!r' if x < 0.01 else '!y' if x < 0.1 else '!g') +
                '{:.0%}'.format(x) + '!e'
                for x in accepts
            ]) + ' ]'
            outarr.append(scorestring)
        if isinstance(progress, list):
            if progress[1]:
                progressstring = (
                    self._strings['progress'] +
                    ': [ {}/{} ]'.format(*progress))
            else:
                progressstring = (
                    self._strings['progress'] + ': [ {} ]'.format(progress[0]))
            outarr.append(progressstring)
        if fitter._emcee_est_t < 0.0:
            outarr.append(self._strings['run_until_converged'])
        elif fitter._emcee_est_t + fitter._bh_est_t > 0.0:
            if fitter._bh_est_t > 0.0 or not fitter._fracking:
                tott = fitter._emcee_est_t + fitter._bh_est_t
            else:
                tott = 2.0 * fitter._emcee_est_t
            timestring = self.get_timestring(tott)
            outarr.append(timestring)
        if acor is not None:
            acorcstr = pretty_num(acor[1], sig=3)
            if acor[0] <= 0.0:
                acorstring = ('!rChain too short for `acor` ({})!e'.format(
                              acorcstr))
            else:
                acortstr = pretty_num(acor[0], sig=3)
                acorbstr = str(int(acor[2]))
                if acor[1] < 2.0:
                    col = '!r'
                elif acor[1] < 5.0:
                    col = '!y'
                else:
                    col = '!g'
                acorstring = col
                acorstring = acorstring + 'Acor Tau (i > {}): {} ({}x)'.format(
                    acorbstr, acortstr, acorcstr)
                acorstring = acorstring + ('!e' if col else '')
            outarr.append(acorstring)
        if psrf is not None and psrf[0] != np.inf:
            psrfstr = pretty_num(psrf[0], sig=4)
            psrfbstr = str(int(psrf[1]))
            if psrf[0] > 2.0:
                col = '!r'
            elif psrf[0] > 1.2:
                col = '!y'
            else:
                col = '!g'
            psrfstring = col
            psrfstring = psrfstring + 'PSRF (i > {}): {}'.format(
                psrfbstr, psrfstr)
            psrfstring = psrfstring + ('!e' if col else '')
            outarr.append(psrfstring)

        if not isinstance(messages, list):
            raise ValueError('`messages` must be list!')
        outarr.extend(messages)

        kmat_extra = 0
        if kmat is not None and kmat.shape[0] > 1:
            kmat_scaled = congrid(kmat, (14, 7), minusone=True,
                                  bounds_error=False)
            kmat_scaled = np.log(kmat_scaled)
            kmat_scaled /= np.max(kmat_scaled)
            kmat_pers = [np.percentile(kmat_scaled, x) for x in (20, 50, 80)]
            kmat_dimi = range(len(kmat_scaled))
            kmat_dimj = range(len(kmat_scaled[0]))
            doodle = '\n╔' + ('═' * len(kmat_scaled)) + '╗   \n'
            doodle += '║' + '║   \n║'.join(
                [''.join([self.ascii_fill(kmat_scaled[i, j], kmat_pers)
                          for i in kmat_dimi]) for j in kmat_dimj]) + '║'
            doodle += '\n╚' + ('═' * len(kmat_scaled)) + '╝   '
            doodle = doodle.splitlines()

            kmat_extra = len(doodle[-1])

        line = ''
        lines = ''
        li = 0
        for i, item in enumerate(outarr):
            oldline = line
            line = line + (' | ' if li > 0 else '') + item
            li = li + 1
            if len(line) > self._wrap_length - kmat_extra:
                li = 1
                lines = lines + '\n' + oldline
                line = item

        lines = lines + '\n' + line

        if kmat is not None and kmat.shape[0] > 1:
            lines = self._lines(lines)
            loff = int(np.floor((len(kmat_scaled[0]) - len(lines)) / 2.0)) + 2
            for li, line in enumerate(doodle):
                if li < loff:
                    continue
                elif li > loff + len(lines) - 1:
                    break
                doodle[li] += lines[li - loff]
            lines = '\n'.join(doodle)

        self.prt(lines, colorify=True, inline=not make_space)

    def get_timestring(self, t):
        """Return estimated time remaining.

        Return a string showing the estimated remaining time based upon
        elapsed times for emcee and fracking.
        """
        td = str(datetime.timedelta(seconds=int(round(t))))
        return (self._strings['estimated_time'] + ': [ ' + td + ' ]')

    def translate(self, text):
        """Translate text to another language."""
        if self._language != 'en':
            try:
                from googletrans import Translator
                translator = Translator()
                ttext, reps = self.rep_ansi(text)
                ttext = translator.translate(ttext, dest=self._language).text
                text = ttext.format(*reps)
            except Exception:
                pass
        return text

    def rep_ansi(self, text):
        """Replace ANSI codes and return the list of codes."""
        patt = re.compile(r'({})'.format(
            '|'.join(['\{.*?\}'] + list(self.ansi.codes.keys()))))
        stext = patt.sub("{}", text)
        matches = patt.findall(text)
        return stext, matches

    def tree(self, my_tree):
        """Pretty print the module dependency trees for each root."""
        for root in my_tree:
            tree_str = json.dumps({root: my_tree[root]},
                                  indent='─ ',
                                  separators=('', ''))
            tree_str = ''.join(
                c for c in tree_str if c not in ['{', '}', '"'])
            tree_str = '\n'.join([
                x.rstrip() for x in tree_str.split('\n') if
                x.strip('─ ') != ''])
            tree_str = '\n'.join(
                [x[::-1].replace('─ ─', '├', 1)[::-1].replace('─', '│') if
                 x.startswith('─ ─') else x.replace('─ ', '') + ':'
                 for x in tree_str.split('\n')])
            lines = ['  ' + x for x in tree_str.split('\n')]
            ll = len(lines)
            for li, line in enumerate(lines):
                if (li < ll - 1 and
                        lines[li + 1].count('│') < line.count('│')):
                    lines[li] = line.replace('├', '└')
            for li, line in enumerate(reversed(lines)):
                if li == 0:
                    lines[ll - li - 1] = line.replace(
                        '│', ' ').replace('├', '└')
                    continue
                lines[ll - li - 1] = ''.join([
                    x if ci > len(lines[ll - li]) - 1 or x not in ['│', '├'] or
                    lines[ll - li][ci] != ' ' else x.replace(
                        '│', ' ').replace(
                            '├', '└') for ci, x in enumerate(line)])
            tree_str = '\n'.join(lines)
            self.prt(tree_str)

    def ascii_fill(self, value, pers):
        """Print a character based on range from 0 - 1."""
        if np.isnan(value) or value < pers[0]:
            return ' '
        if np.isnan(value) or value < pers[1]:
            return '.'
        elif value < pers[2]:
            return '*'
        else:
            return '#'
