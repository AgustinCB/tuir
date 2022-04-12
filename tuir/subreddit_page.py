# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import re
import time

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

from . import docs
from .content import SubredditContent
from .page import Page, PageController, logged_in
from .objects import Navigator, Command
from .exceptions import TemporaryFileError


class SubredditController(PageController):
    character_map = {}


class SubredditPage(Page):
    BANNER = docs.BANNER_SUBREDDIT
    FOOTER = docs.FOOTER_SUBREDDIT

    # Format separators, used by _create_format and _draw_item_format for
    # attribute handling logic
    FORMAT_SEP = r'<>/{}[]()|_-~'

    FORMAT_LIST = ''
    name = 'subreddit'

    def __init__(self, reddit, term, config, oauth, name):
        """
        Params:
            name (string): Name of subreddit to open
        """
        super(SubredditPage, self).__init__(reddit, term, config, oauth)

        self.controller = SubredditController(self, keymap=config.keymap)
        self.content = SubredditContent.from_name(reddit, self.config, name, term.loader)
        self.nav = Navigator(self.content.get)
        self.toggled_subreddit = None

        self.FORMAT_LIST = self._create_format_list()

    # Split this out to a function mostly to simplify testing
    def _create_format_list(self):
        if self.config['subreddit_format']:
            # Split the list between %., newlines, and separator characters to
            # treat them separately
            format_list = re.split(r'(%.|[\n' + re.escape(self.FORMAT_SEP) + '])',
                    self.config['subreddit_format'], re.DOTALL)

            # Clean the list of null items. We don't need to join this list
            # together again, so this is safe.
            # https://stackoverflow.com/q/2197451
            return [item for item in format_list if item != '']
        else:
            return None

    def handle_selected_page(self):
        """
        Open all selected pages in subwindows except other subreddit pages.
        """
        if not self.selected_page:
            pass
        elif self.selected_page.name in ('subscription', 'submission', 'inbox'):
            # Launch page in a subwindow
            self.selected_page = self.selected_page.loop()
        elif self.selected_page.name == 'subreddit':
            # Replace the current page
            self.active = False
        else:
            raise RuntimeError(self.selected_page.name)

    def refresh_content(self, order=None, name=None):
        """
        Re-download all submissions and reset the page index
        """
        order = order or self.content.order

        # Preserve the query if staying on the current page
        if name is None:
            query = self.content.query
        else:
            query = None

        name = name or self.content.name

        # Hack to allow an order specified in the name by prompt_subreddit() to
        # override the current default
        if order == 'ignore':
            order = None

        with self.term.loader('Refreshing page'):
            self.content = SubredditContent.from_name(
                self.reddit, self.config, name,
                self.term.loader, order=order, query=query)
        if not self.term.loader.exception:
            self.nav = Navigator(self.content.get)

    @SubredditController.register(Command('SORT_1'))
    def sort_content_hot(self):
        if self.content.query:
            self.refresh_content(order='relevance')
        else:
            self.refresh_content(order='hot')

    @SubredditController.register(Command('SORT_2'))
    def sort_content_top(self):
        order = self._prompt_period('top')
        if order is None:
            self.term.show_notification('Invalid option')
        else:
            self.refresh_content(order=order)

    @SubredditController.register(Command('SORT_3'))
    def sort_content_rising(self):
        if self.content.query:
            order = self._prompt_period('comments')
            if order is None:
                self.term.show_notification('Invalid option')
            else:
                self.refresh_content(order=order)
        else:
            self.refresh_content(order='rising')

    @SubredditController.register(Command('SORT_4'))
    def sort_content_new(self):
        self.refresh_content(order='new')

    @SubredditController.register(Command('SORT_5'))
    def sort_content_controversial(self):
        if self.content.query:
            self.term.flash()
        else:
            order = self._prompt_period('controversial')
            if order is None:
                self.term.show_notification('Invalid option')
            else:
                self.refresh_content(order=order)


    @SubredditController.register(Command('SORT_6'))
    def sort_content_gilded(self):
        if self.content.query:
            self.term.flash()
        else:
            self.refresh_content(order='gilded')

    @SubredditController.register(Command('SUBREDDIT_SEARCH'))
    def search_subreddit(self, name=None):
        """
        Open a prompt to search the given subreddit
        """
        name = name or self.content.name

        query = self.term.prompt_input('Search {0}: '.format(name))
        if not query:
            return

        with self.term.loader('Searching'):
            self.content = SubredditContent.from_name(
                self.reddit, self.config, name, self.term.loader, query=query)
        if not self.term.loader.exception:
            self.nav = Navigator(self.content.get)

    @SubredditController.register(Command('SUBREDDIT_FRONTPAGE'))
    def show_frontpage(self):
        """
        If on a subreddit, remember it and head back to the front page.
        If this was pressed on the front page, go back to the last subreddit.
        """

        if self.content.name != '/r/front':
            target = '/r/front'
            self.toggled_subreddit = self.content.name
        else:
            target = self.toggled_subreddit

        # target still may be empty string if this command hasn't yet been used
        if target is not None:
            self.refresh_content(order='ignore', name=target)

    @SubredditController.register(Command('SUBREDDIT_OPEN'))
    def open_submission(self, url=None):
        """
        Select the current submission to view posts.
        """
        if url is None:
            data = self.get_selected_item()
            url = data['permalink']
            if data.get('url_type') == 'selfpost':
                self.config.history.add(data['url_full'])
        self.selected_page = self.open_submission_page(url)

    @SubredditController.register(Command('SUBREDDIT_DOWNLOAD'))
    def download_image(self):
        """
        Download the link contained in the selected item in chafa.

        If there is more than one link contained in the item, prompt the user
        to choose which link to open.
        """
        data = self.get_selected_item()
        if data['type'] == 'Submission':
            link = data['url_full']
            if link:
                self.config.history.add(link)
                self.term.download_content(link)
        elif data['type'] == 'Comment':
            link = data['url_full']
            if link:
                self.term.download_content(link)
        else:
            self.term.flash()

    @SubredditController.register(Command('SUBREDDIT_OPEN_CONTENT'))
    def open_content(self):
        """
        Open the image contained in the selected item in chafa.

        If there is more than one link contained in the item, prompt the user
        to choose which link to open.
        """
        data = self.get_selected_item()
        if data['type'] == 'Submission':
            link = data['url_full']
            if link:
                self.config.history.add(link)
                self.term.open_content(link, data)
        elif data['type'] == 'Comment':
            link = data['url_full']
            if link:
                self.term.open_content(link, data)
        else:
            self.term.flash()

    @SubredditController.register(Command('SUBREDDIT_OPEN_IN_BROWSER'))
    def open_link(self):
        """
        Open a link with the webbrowser
        """

        data = self.get_selected_item()
        if data['url_type'] == 'selfpost':
            self.open_submission()
        elif data['url_type'] == 'x-post subreddit':
            self.refresh_content(order='ignore', name=data['xpost_subreddit'])
        elif data['url_type'] == 'x-post submission':
            self.open_submission(url=data['url_full'])
            self.config.history.add(data['url_full'])
        else:
            self.term.open_link(data['url_full'])
            self.config.history.add(data['url_full'])

    @SubredditController.register(Command('SUBREDDIT_POST'))
    @logged_in
    def post_submission(self):
        """
        Post a new submission to the given subreddit.
        """
        # Check that the subreddit can be submitted to
        name = self.content.name
        if '+' in name or name in ('/r/all', '/r/front', '/r/me', '/u/saved'):
            self.term.show_notification("Can't post to {0}".format(name))
            return

        submission_info = docs.SUBMISSION_FILE.format(name=name)
        with self.term.open_editor(submission_info) as text:
            if not text:
                self.term.show_notification('Canceled')
                return
            elif '\n' not in text:
                self.term.show_notification('Missing body')
                return

            title, content = text.split('\n', 1)
            with self.term.loader('Posting', delay=0):
                submission = self.reddit.submit(name, title, text=content,
                                                raise_captcha_exception=True)
                # Give reddit time to process the submission
                time.sleep(2.0)
            if self.term.loader.exception:
                raise TemporaryFileError()

        if not self.term.loader.exception:
            # Open the newly created submission
            self.selected_page = self.open_submission_page(submission=submission)

    @SubredditController.register(Command('SUBREDDIT_HIDE'))
    @logged_in
    def hide(self):
        data = self.get_selected_item()
        if not hasattr(data["object"], 'hide'):
            self.term.flash()
        elif data['hidden']:
            with self.term.loader('Unhiding'):
                data['object'].unhide()
                data['hidden'] = False
        else:
            with self.term.loader('Hiding'):
                data['object'].hide()
                data['hidden'] = True

    def _submission_attr(self, data):
        if data['url_full'] in self.config.history:
            return self.term.attr('SubmissionTitleSeen')
        else:
            return self.term.attr('SubmissionTitle')

    def _url_str(self, data):
        # Both of these url_types indicate a URL of a subreddit/comment, and
        # self.subreddit should be used as the display url
        if data['url_type'] == 'selfpost' or \
                data['url_type'].startswith('x-post'):
            return data['url']
        else:
            return urlparse(data['url_full']).hostname

    def _url_attr(self, data):
        if data['url_full'] in self.config.history:
            return self.term.attr('LinkSeen')
        else:
            return self.term.attr('Link')

    def _gold_str(self, data):
        if data['gold'] > 1:
            return self.term.gilded + 'x{}'.format(data['gold'])
        elif data['gold'] == 1:
            return self.term.gilded
        else:
            return ''

    def _draw_item_format(self, win, data, valid_rows, offset):
        first = True

        # Remember whether or not the last character printed was a space. If it
        # was, printing more spaces should be avoided.
        last_was_space = False

        for item in self.FORMAT_LIST:
            col = 1 if first else None

            # We don't want to print consecutive spaces, so check if a space
            # was the last character printed, and skip this iteration if a
            # space is to be printed
            if last_was_space and item == ' ':
                # coverage reports this as never executing, despite
                # test_subreddit_page__draw_item_format testing for it, and pdb
                # confirming the line is executed
                continue

            last_was_space = True

            if item == "%i":
                self.term.add_line(win, str(data['index']),
                                   row=offset, col=col,
                                   attr=self._submission_attr(data))
                last_was_space = False
            elif item == "%t":
                self.term.add_line(win, data['title'],
                                   row=offset, col=col,
                                   attr=self._submission_attr(data))
                last_was_space = False
            elif item == "%s":
                self.term.add_line(win, str(data['score']),
                                   row=offset, col=col,
                                   attr=self.term.attr('Score'))
                last_was_space = False
            elif item == "%v":
                arrow = self.term.get_arrow(data['likes'])

                self.term.add_line(win, arrow[0],
                                   row=offset, col=col,
                                   attr=arrow[1])
                last_was_space = False
            elif item == "%c":
                self.term.add_line(win, data['comments'],
                                   row=offset, col=col,
                                   attr=self.term.attr('CommentCount'))
                last_was_space = False
            elif item == "%r":
                self.term.add_line(win, data['created'],
                                   row=offset, col=col,
                                   attr=self.term.attr('Created'))
                last_was_space = False
            elif item == "%R":
                self.term.add_line(win, data['created_exact'],
                                   row=offset, col=col,
                                   attr=self.term.attr('Created'))
                last_was_space = False
            elif item == "%e":
                self.term.add_line(win, data['edited'],
                                   row=offset, col=col,
                                   attr=self.term.attr('Created'))
                last_was_space = False
            elif item == "%E":
                self.term.add_line(win, data['edited_exact'],
                                   row=offset, col=col,
                                   attr=self.term.attr('Created'))
                last_was_space = False
            elif item == "%a":
                self.term.add_line(win, data['author'],
                                   row=offset, col=col,
                                   attr=self.term.attr('SubmissionAuthor'))
                last_was_space = False
            elif item == "%S":
                self.term.add_line(win, "/r/" + data['subreddit'],
                                   row=offset, col=col,
                                   attr=self.term.attr('SubmissionSubreddit'))
                last_was_space = False
            elif item == "%u":
                self.term.add_line(win, self._url_str(data),
                                   row=offset, col=col,
                                   attr=self._url_attr(data))
                last_was_space = False
            elif item == "%U":
                self.term.add_line(win, data['url'],
                                   row=offset, col=col,
                                   attr=self._url_attr(data))
                last_was_space = False
            elif item == "%A":
                if data['saved']:
                    self.term.add_line(win, '[saved]',
                                       row=offset, col=col,
                                       attr=self.term.attr('Saved'))

                    last_was_space = False
            elif item == "%h":
                if data['hidden']:
                    self.term.add_line(win, '[hidden]',
                                       row=offset, col=col,
                                       attr=self.term.attr('Hidden'))

                    last_was_space = False
            elif item == "%T":
                if data['stickied']:
                    self.term.add_line(win, '[stickied]',
                                       row=offset, col=col,
                                       attr=self.term.attr('Stickied'))

                    last_was_space = False
            elif item == "%g":
                if data['gold'] > 0:
                    self.term.add_line(win, self._gold_str(data),
                                       row=offset, col=col,
                                       attr=self.term.attr('Gold'))
                    last_was_space = False

            elif item == "%n":
                if data['nsfw']:
                    self.term.add_line(win, 'NSFW',
                                       row=offset, col=col,
                                       attr=self.term.attr('NSFW'))

                    last_was_space = False
            elif item == "%f":
                if data['flair']:
                    self.term.add_line(win, data['flair'],
                                       row=offset, col=col,
                                       attr=self.term.attr('SubmissionFlair'))

                    last_was_space = False
            elif item == "%F":
                if data['flair']:
                    self.term.add_line(win, data['flair'],
                                       row=offset, col=col,
                                       attr=self.term.attr('SubmissionFlair'))

                    # These ugly if's write a space if necessary. It is
                    # necessary if there are more flairlike strings to write.
                    if (data['saved'] or data['hidden'] or
                        data['stickied'] or data['gold'] or
                        data['nsfw']):
                        self.term.add_space(win)

                    last_was_space = False

                if data['saved']:
                    self.term.add_line(win, '[saved]',
                                       row=offset, col=col,
                                       attr=self.term.attr('Saved'))

                    if (data['hidden'] or data['stickied'] or
                        data['gold'] or data['nsfw']):
                        self.term.add_space(win)

                    last_was_space = False

                if data['hidden']:
                    self.term.add_line(win, '[hidden]',
                                       row=offset, col=col,
                                       attr=self.term.attr('Hidden'))

                    if (data['stickied'] or data['gold'] or
                        data['nsfw']):
                        self.term.add_space(win)

                    last_was_space = False

                if data['stickied']:
                    self.term.add_line(win, '[stickied]',
                                       row=offset, col=col,
                                       attr=self.term.attr('Stickied'))

                    if data['gold'] or data['nsfw']:
                        self.term.add_space(win)

                    last_was_space = False

                if data['gold']:
                    self.term.add_line(win, self._gold_str(data),
                                       row=offset, col=col,
                                       attr=self.term.attr('Gold'))

                    if data['nsfw']:
                        self.term.add_space(win)

                    last_was_space = False

                if data['nsfw']:
                    self.term.add_line(win, 'NSFW',
                                       row=offset, col=col,
                                       attr=self.term.attr('NSFW'))

                    last_was_space = False
            elif item == "\n":
                first = True
                offset += 1

                continue
            else: # Write something else that isn't in the data dict
                # Make certain "separator" characters use the Separator
                # attribute
                if item in self.FORMAT_SEP:
                    self.term.add_line(win, item,
                                       row=offset, col=col,
                                       attr=self.term.attr('Separator'))
                else:
                    self.term.add_line(win, item,
                                       row=offset, col=col,
                                       attr=None)

                if item != ' ':
                    last_was_space = False

            first = False

    def _draw_item_default(self, win, data, n_rows, n_cols, valid_rows, offset):
        """
        Draw items with default look and feel
        """

        n_title = len(data['split_title'])

        if data['url_full'] in self.config.history:
            attr = self.term.attr('SubmissionTitleSeen')
        else:
            attr = self.term.attr('SubmissionTitle')

        for row, text in enumerate(data['split_title'], start=offset):
            if row in valid_rows:
                self.term.add_line(win, text, row, 1, attr)

        row = n_title + offset

        if data['url_full'] in self.config.history:
            attr = self.term.attr('LinkSeen')
        else:
            attr = self.term.attr('Link')

        if row in valid_rows:
            self.term.add_line(win, '{url}'.format(**data), row, 1, attr)

        row = n_title + offset + 1

        if row in valid_rows:
            attr = self.term.attr('Score')
            self.term.add_line(win, '{score} pts'.format(**data), row, 1, attr)
            self.term.add_space(win)

            arrow, attr = self.term.get_arrow(data['likes'])
            self.term.add_line(win, arrow, attr=attr)
            self.term.add_space(win)

            attr = self.term.attr('Created')
            self.term.add_line(win, '{created}{edited}'.format(**data), attr=attr)

            if data['comments'] is not None:
                attr = self.term.attr('Separator')
                self.term.add_space(win)
                self.term.add_line(win, '-', attr=attr)

                attr = self.term.attr('CommentCount')
                self.term.add_space(win)
                self.term.add_line(win, '{comments} comments'.format(**data), attr=attr)

            if data['saved']:
                attr = self.term.attr('Saved')
                self.term.add_space(win)
                self.term.add_line(win, '[saved]', attr=attr)

            if data['hidden']:
                attr = self.term.attr('Hidden')
                self.term.add_space(win)
                self.term.add_line(win, '[hidden]', attr=attr)

            if data['stickied']:
                attr = self.term.attr('Stickied')
                self.term.add_space(win)
                self.term.add_line(win, '[stickied]', attr=attr)

            if data['gold']:
                attr = self.term.attr('Gold')
                self.term.add_space(win)
                count = 'x{}'.format(data['gold']) if data['gold'] > 1 else ''
                text = self.term.gilded + count
                self.term.add_line(win, text, attr=attr)

            if data['nsfw']:
                attr = self.term.attr('NSFW')
                self.term.add_space(win)
                self.term.add_line(win, 'NSFW', attr=attr)

        row = n_title + offset + 2

        if row in valid_rows:
            attr = self.term.attr('SubmissionAuthor')
            self.term.add_line(win, '{author}'.format(**data), row, 1, attr)
            self.term.add_space(win)

            attr = self.term.attr('SubmissionSubreddit')
            self.term.add_line(win, '/r/{subreddit}'.format(**data), attr=attr)

            if data['flair']:
                attr = self.term.attr('SubmissionFlair')
                self.term.add_space(win)
                self.term.add_line(win, '{flair}'.format(**data), attr=attr)

    def _draw_item(self, win, data, inverted):
        n_rows, n_cols = win.getmaxyx()
        n_cols -= 1  # Leave space for the cursor in the first column

        # Handle the case where the window is not large enough to fit the data.
        valid_rows = range(0, n_rows)
        offset = 0 if not inverted else - (data['n_rows'] - n_rows)

        # TODO - this assumes default doesn't have a subreddit_format. In the
        # future it should, and when it does it will break this if
        if self.config['subreddit_format']:
            self._draw_item_format(win, data, valid_rows, offset)
        else:
            self._draw_item_default(win, data, n_rows, n_cols, valid_rows, offset)

        attr = self.term.attr('CursorBlock')

        for y in range(n_rows):
            self.term.addch(win, y, 0, str(' '), attr)
