#/usr/bin/python
#
# Copyright 2008 Dan Smith <dsmith@danplanet.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

if __name__ == "__main__":
    import sys
    sys.path.insert(0, "..")

import threading

import gtk
from gobject import TYPE_INT, \
    TYPE_DOUBLE as TYPE_FLOAT, \
    TYPE_STRING, \
    TYPE_BOOLEAN
import gobject

from chirpui import common, shiftdialog
from chirp import chirp_common, errors

def handle_toggle(_, path, store, col):
    store[path][col] = not store[path][col]    

def handle_ed(_, iter, new, store, col):
    old, = store.get(iter, col)
    if old != new:
        store.set(iter, col, new)
        return True
    else:
        return False

class ValueErrorDialog(gtk.MessageDialog):
    def __init__(self, exception, **args):
        gtk.MessageDialog.__init__(self, buttons=gtk.BUTTONS_OK, **args)
        self.set_property("text", "Invalid value for this field")
        self.format_secondary_text(str(exception))

def iter_prev(store, iter):
    row = store.get_path(iter)[0]
    if row == 0:
        return None
    return store.get_iter((row - 1,))

class MemoryEditor(common.Editor):
    cols = [
        ("_empty"    , TYPE_BOOLEAN,gtk.CellRendererText,  ),
        ("Loc"       , TYPE_INT,    gtk.CellRendererText,  ),
        ("_extd"     , TYPE_STRING, gtk.CellRendererText,  ),
        ("Name"      , TYPE_STRING, gtk.CellRendererText,  ), 
        ("Frequency" , TYPE_FLOAT,  gtk.CellRendererText,  ),
        ("Tone Mode" , TYPE_STRING, gtk.CellRendererCombo, ),
        ("Tone"      , TYPE_FLOAT,  gtk.CellRendererCombo, ),
        ("ToneSql"   , TYPE_FLOAT,  gtk.CellRendererCombo, ),
        ("DTCS Code" , TYPE_INT,    gtk.CellRendererCombo, ),
        ("DTCS Pol"  , TYPE_STRING, gtk.CellRendererCombo, ),
        ("Duplex"    , TYPE_STRING, gtk.CellRendererCombo, ),
        ("Offset"    , TYPE_FLOAT,  gtk.CellRendererText,  ),
        ("Mode"      , TYPE_STRING, gtk.CellRendererCombo, ),
        ("Tune Step" , TYPE_FLOAT,  gtk.CellRendererCombo, ),
        ("Skip"      , TYPE_STRING, gtk.CellRendererCombo, ),
        ("Bank"      , TYPE_STRING, gtk.CellRendererCombo, ),
        ("Bank Index", TYPE_INT,    gtk.CellRendererText,  ),
        ]

    defaults = {
        "Name"      : "",
        "Frequency" : 146.010,
        "Tone"      : 88.5,
        "ToneSql"   : 88.5,
        "DTCS Code" : 23,
        "DTCS Pol"  : "NN",
        "Duplex"    : "",
        "Offset"    : 0.0,
        "Mode"      : "FM",
        "Tune Step" : 10.0,
        "Tone Mode" : "",
        "Skip"      : "",
        "Bank"      : "",
        "Bank Index": 0,
        }

    choices = {
        "Tone" : chirp_common.TONES,
        "ToneSql" : chirp_common.TONES,
        "DTCS Code" : chirp_common.DTCS_CODES,
        "DTCS Pol" : ["NN", "NR", "RN", "RR"],
        "Mode" : chirp_common.MODES,
        "Duplex" : ["", "-", "+", "split"],
        "Tune Step" : chirp_common.TUNING_STEPS,
        "Tone Mode" : ["", "Tone", "TSQL", "DTCS"],
        "Skip" : chirp_common.SKIP_VALUES,
        }
    
    def ed_name(self, _, __, new, ___):
        return self.rthread.radio.filter_name(new)

    def ed_freq(self, _, path, new, __):
        def set_offset(path, offset):
            if offset > 0:
                dup = "+"
            elif offset == 0:
                dup = ""
            else:
                dup = "-"
                offset *= -1

            iter = self.store.get_iter(path)
            
            if offset:
                self.store.set(iter, self.col("Offset"), offset)

            self.store.set(iter, self.col("Duplex"), dup)

        def set_ts(path, ts):
            iter = self.store.get_iter(path)

            self.store.set(iter, self.col("Tune Step"), ts)

        try:
            new = float(new)
        except ValueError, e:
            print e
            new = None

        if chirp_common.is_6_25(new):
            set_ts(path, 6.25)
        elif chirp_common.is_12_5(new):
            set_ts(path, 12.5)

        if new:
            set_offset(path, 0)
            band = int(new / 100)
            if chirp_common.STD_OFFSETS.has_key(band):
                offsets = chirp_common.STD_OFFSETS[band]
                for lo, hi, offset in offsets:
                    if new < hi and new > lo:
                        set_offset(path, offset)
                        break

        return new

    def ed_loc(self, _, path, new, __):
        iter = self.store.get_iter(path)
        curloc, = self.store.get(iter, self.col("Loc"))

        job = common.RadioJob(None, "erase_memory", curloc)
        job.set_desc("Erasing memory %i" % curloc)
        self.rthread.submit(job)

        self.need_refresh = True

        return new

    def edited(self, rend, path, new, cap):
        if self.read_only:
            common.show_error("Unable to make changes to this model")
            return

        colnum = self.col(cap)
        funcs = {
            "Loc" : self.ed_loc,
            "Name" : self.ed_name,
            "Frequency" : self.ed_freq,
            }

        if funcs.has_key(cap):
            new = funcs[cap](rend, path, new, colnum)

        if new is None:
            print "Bad value for %s: %s" % (cap, new)
            return

        if self.store.get_column_type(colnum) == TYPE_INT:
            new = int(new)
        elif self.store.get_column_type(colnum) == TYPE_FLOAT:
            new = float(new)
        elif self.store.get_column_type(colnum) == TYPE_BOOLEAN:
            new = bool(new)
        elif self.store.get_column_type(colnum) == TYPE_STRING:
            if new == "(None)":
                new = ""

        iter = self.store.get_iter(path)

        if not handle_ed(rend, iter, new, self.store, self.col(cap)) and \
                cap != "Frequency":
            # No change was made
            # For frequency, we make an exception, since the handler might
            # have altered the duplex.  That needs to be fixed.
            return


        def cb(result):
            if isinstance(result, Exception):
                # FIXME: This can't be in the thread
                dlg = ValueErrorDialog(result)
                dlg.run()
                dlg.destroy()
                self.prefill()
            elif self.need_refresh:
                self.prefill()
                self.need_refresh = False

            # pylint: disable-msg=E1101
            self.emit('changed')

        mem = self._get_memory(iter)
        job = common.RadioJob(cb, "set_memory", mem)
        job.set_desc("Writing memory %i" % mem.number)
        self.rthread.submit(job)

        self.store.set(iter, self.col("_empty"), False)

    def _render(self, colnum, val, iter=None):
        if colnum == self.col("Frequency"):
            val = "%.5f" % val
        elif colnum == self.col("DTCS Code"):
            val = "%03i" % int(val)
        elif colnum == self.col("Offset"):
            val = "%.3f" % val
        elif colnum in [self.col("Tone"), self.col("ToneSql")]:
            val = "%.1f" % val
        elif colnum in [self.col("Tone Mode"), self.col("Duplex")]:
            if not val:
                val = "(None)"
        elif colnum == self.col("Loc") and iter is not None:
            extd, = self.store.get(iter, self.col("_extd"))
            if extd:
                val = extd

        return val

    def render(self, _, rend, model, iter, colnum):
        vals = model.get(iter, *tuple(range(0, len(self.cols))))
        val = vals[colnum]

        def _enabled(sensitive):
            rend.set_property("sensitive", sensitive)

        def d_unless_tmode(tmode):
            _enabled(vals[self.col("Tone Mode")] == tmode)

        def d_unless_dup():
            _enabled(vals[self.col("Duplex")])

        def d_if_mode(mode):
            if vals[self.col("Mode")] == mode:
                _enabled(False)

        def d_unless_positive_bidx():
            _enabled(int(val) != -1)

        val = self._render(colnum, val, iter)
        rend.set_property("text", "%s" % val)

        if colnum == self.col("DTCS Code"):
            d_unless_tmode("DTCS")
        elif colnum == self.col("DTCS Pol"):
            d_unless_tmode("DTCS")
        elif colnum == self.col("Tone"):
            d_unless_tmode("Tone")
            d_if_mode("DV")
        elif colnum == self.col("ToneSql"):
            d_unless_tmode("TSQL")
            d_if_mode("DV")
        elif colnum == self.col("Offset"):
            d_unless_dup()
        elif colnum == self.col("Bank Index"):
            d_unless_positive_bidx()

        _enabled(not vals[self.col("_empty")])

    def insert_easy(self, store, _iter, delta):
        if delta < 0:
            iter = store.insert_before(_iter)
        else:
            iter = store.insert_after(_iter)

        newpos, = store.get(_iter, self.col("Loc"))
        newpos += delta

        print "Insert easy: %i" % delta

        line = []
        for key, val in self.defaults.items():
            line.append(self.col(key))
            line.append(val)
        
        store.set(iter,
                  0, newpos,
                  *tuple(line))

        mem = self._get_memory(iter)
        job = common.RadioJob(None, "set_memory", mem)
        job.set_desc("Writing memory %i" % mem.number)
        self.rthread.submit(job)

    def insert_hard(self, store, _iter, delta):
        txt = """This operation requires moving all subsequent channels
by one spot until an empty location is reached.  This can take a LONG
time.  Are you sure you want to do this?"""
        if not common.ask_yesno_question(txt):
            return

        if delta <= 0:
            iter = _iter
        else:
            iter = store.iter_next(_iter)

        pos, = store.get(iter, self.col("Loc"))

        sd = shiftdialog.ShiftDialog(self.rthread)

        if delta == 0:
            sd.delete(pos)
            sd.destroy()
            self.prefill()
        else:
            sd.insert(pos)
            sd.destroy()
            mem = chirp_common.Memory()
            mem.number = pos
            mem.empty = True
            job = common.RadioJob(lambda x: self.prefill(), "set_memory", mem)
            job.set_desc("Adding memory %i" % mem.number)
            self.rthread.submit(job)


    def mh(self, _action):
        action = _action.get_name()
        store, iter = self.view.get_selection().get_selected()
        cur_pos, = store.get(iter, self.col("Loc"))

        if action == "insert_next":
            self.insert_hard(store, iter, 1)
        elif action == "insert_prev":
            self.insert_hard(store, iter, -1)
        elif action == "delete":
            store.set(iter, self.col("_empty"), True)
            job = common.RadioJob(None, "erase_memory", cur_pos)
            job.set_desc("Erasing memory %i" % cur_pos)
            self.rthread.submit(job)

            def handler(mem):
                if not isinstance(mem, Exception):
                    if not mem.empty or self.show_empty:
                        gobject.idle_add(self.set_memory, mem)

            job = common.RadioJob(handler, "get_memory", cur_pos)
            job.set_desc("Getting memory %s" % cur_pos)
            self.rthread.submit(job)

            if not self.show_empty:
                store.remove(iter)

        elif action == "delete_s":
            self.insert_hard(store, iter, 0)

    def make_context_menu(self):
        menu_xml = """
<ui>
  <popup name="Menu">
    <menuitem action="insert_prev"/>
    <menuitem action="insert_next"/>
    <menuitem action="delete"/>
    <menuitem action="delete_s"/>
  </popup>
</ui>
"""

        actions = [
            ("insert_prev",None,"Insert row above",None,None, self.mh),
            ("insert_next",None,"Insert row below",None,None, self.mh),
            ("delete", None, "Delete", None, None, self.mh),
            ("delete_s", None, "Delete (and shift up)", None, None, self.mh),
            ]

        ag = gtk.ActionGroup("Menu")
        ag.add_actions(actions)

        uim = gtk.UIManager()
        uim.insert_action_group(ag, 0)
        uim.add_ui_from_string(menu_xml)

        return uim.get_widget("/Menu")

    def click_cb(self, view, event):
        if event.button != 3:
            return

        menu = self.make_context_menu()
        menu.popup(None, None, None, event.button, event.time)
        
    def get_column_visible(self, col):
        column = self.view.get_column(col)
        return column.get_visible()

    def set_column_visible(self, col, visible):
        column = self.view.get_column(col)
        column.set_visible(visible)
    
    def make_editor(self):
        types = tuple([x[1] for x in self.cols])
        self.store = gtk.ListStore(*types)

        self.view = gtk.TreeView(self.store)
        self.view.set_rules_hint(True)

        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.add(self.view)

        i = 0
        for _cap, _type, _rend in self.cols:
            rend = _rend()
            if _type == TYPE_BOOLEAN:
                #rend.set_property("activatable", True)
                #rend.connect("toggled", handle_toggle, self.store, i)
                col = gtk.TreeViewColumn(_cap, rend, active=i)
            elif _rend == gtk.CellRendererCombo:
                if isinstance(self.choices[_cap], gtk.ListStore):
                    choices = self.choices[_cap]
                else:
                    choices = gtk.ListStore(TYPE_STRING, TYPE_STRING)
                    for choice in self.choices[_cap]:
                        choices.append([choice, self._render(i, choice)])
                rend.set_property("model", choices)
                rend.set_property("text-column", 1)
                rend.set_property("editable", True)
                rend.set_property("has-entry", False)
                rend.connect("edited", self.edited, _cap)
                col = gtk.TreeViewColumn(_cap, rend, text=i)
                col.set_cell_data_func(rend, self.render, i)
            else:
                rend.set_property("editable", True)
                rend.connect("edited", self.edited, _cap)
                col = gtk.TreeViewColumn(_cap, rend, text=i)
                col.set_cell_data_func(rend, self.render, i)
                
            col.set_sort_column_id(i)
            col.set_resizable(True)
            col.set_min_width(1)
            col.set_visible(not _cap.startswith("_"))
            self.view.append_column(col)

            i += 1

        self.store.set_sort_column_id(self.col("Loc"), gtk.SORT_ASCENDING)

        self.view.show()
        sw.show()

        self.view.connect("button_press_event", self.click_cb)

        return sw

    def col(self, caption):
        try:
            return self._cached_cols[caption]
        except KeyError:
            raise Exception("Internal Error: Column %s not found" % caption)

    def prefill(self):
        self.store.clear()

        lo = int(self.lo_limit_adj.get_value())
        hi = int(self.hi_limit_adj.get_value())

        def handler(mem):
            if not isinstance(mem, Exception):
                if not mem.empty or self.show_empty:
                    gobject.idle_add(self.set_memory, mem)

        for i in range(lo, hi+1):
            job = common.RadioJob(handler, "get_memory", i)
            job.set_desc("Getting memory %s" % i)
            self.rthread.submit(job, 2)

        if self.show_special:
            for i in self.rthread.radio.get_special_locations():
                job = common.RadioJob(handler, "get_memory", i)
                job.set_desc("Getting channel %s" % i)
                self.rthread.submit(job, 2)

    def _set_memory(self, iter, memory):
        try:
            if memory.bank is None:
                bank = ""
            else:
                pathstr = "%i" % (memory.bank + 1)
                bi = self.choices["Bank"].get_iter_from_string(pathstr)
                bank, = self.choices["Bank"].get(bi, 1)
        except Exception, e:
            common.log_exception()
            print "Unable to get bank: %s" % e
            bank = ""

        self.store.set(iter,
                       self.col("_empty"), memory.empty,
                       self.col("Loc"), memory.number,
                       self.col("_extd"), memory.extd_number,
                       self.col("Name"), memory.name,
                       self.col("Frequency"), memory.freq,
                       self.col("Tone Mode"), memory.tmode,
                       self.col("Tone"), memory.rtone,
                       self.col("ToneSql"), memory.ctone,
                       self.col("DTCS Code"), memory.dtcs,
                       self.col("DTCS Pol"), memory.dtcs_polarity,
                       self.col("Duplex"), memory.duplex,
                       self.col("Offset"), memory.offset,
                       self.col("Mode"), memory.mode,
                       self.col("Tune Step"), memory.tuning_step,
                       self.col("Skip"), memory.skip,
                       self.col("Bank"), bank,
                       self.col("Bank Index"), memory.bank_index)

    def set_memory(self, memory):
        iter = self.store.get_iter_first()

        while iter is not None:
            loc, = self.store.get(iter, self.col("Loc"))
            if loc == memory.number:
                return self._set_memory(iter, memory)

            iter = self.store.iter_next(iter)

        iter = self.store.append()
        self._set_memory(iter, memory)

    def clear_memory(self, number):
        iter = self.store.get_iter_first()
        while iter:
            loc, = self.store.get(iter, self.col("Loc"))
            if loc == number:
                print "Deleting %i" % number
                # FIXME: Make the actual remove happen on callback
                self.store.remove(iter)
                job = common.RadioJob(None, "erase_memory", number)
                job.set_desc("Erasing memory %i" % number)
                self.rthread.submit()
                break
            iter = self.store.iter_next(iter)

    def _set_mem_vals(self, mem, vals, iter):
        def get_bank_index(name):
            bidx = 0
            banks = self.choices["Bank"]
            iter = banks.get_iter_first()
            iter = banks.iter_next(iter)
            while iter:
                _bank, = banks.get(iter, 1)
                if name == _bank:
                    break
                iter = banks.iter_next(iter)
                bidx += 1

            return bidx

        bank = vals[self.col("Bank")]
        if bank is "":
            bidx = None
            bank_index = vals[self.col("Bank Index")]
        else:
            bidx = get_bank_index(bank)
            if vals[self.col("Bank Index")] == -1 and \
                    self.rthread.radio.get_features().has_bank_index:
                bank_index = self.rthread.radio.get_available_bank_index(bidx)
                print "Chose %i index for bank %s" % (bank_index, bank)
                self.store.set(iter, self.col("Bank Index"), bank_index)
            else:
                bank_index = vals[self.col("Bank Index")]

        mem.freq = vals[self.col("Frequency")]
        mem.number = vals[self.col("Loc")]
        if mem.number < 0:
            mem.extd_number = vals[self.col("_extd")]
        mem.name = vals[self.col("Name")]
        mem.vfo = 0
        mem.rtone = vals[self.col("Tone")]
        mem.ctone = vals[self.col("ToneSql")]
        mem.dtcs = vals[self.col("DTCS Code")]
        mem.tmode = vals[self.col("Tone Mode")]
        mem.dtcs_polarity = vals[self.col("DTCS Pol")]
        mem.duplex = vals[self.col("Duplex")]
        mem.offset = vals[self.col("Offset")]
        mem.mode = vals[self.col("Mode")]
        mem.tuning_step = vals[self.col("Tune Step")]
        mem.skip = vals[self.col("Skip")]
        mem.bank = bidx
        mem.bank_index = bank_index

    def _get_memory(self, iter):
        vals = self.store.get(iter, *range(0, len(self.cols)))
        mem = chirp_common.Memory()
        self._set_mem_vals(mem, vals, iter)

        return mem

    def make_controls(self, min, max):
        hbox = gtk.HBox(False, 2)

        lab = gtk.Label("Memory range:")
        lab.show()
        hbox.pack_start(lab, 0, 0, 0)

        self.lo_limit_adj = gtk.Adjustment(min, min, max+1, 1, 10)
        lo = gtk.SpinButton(self.lo_limit_adj)
        lo.show()
        hbox.pack_start(lo, 0, 0, 0)

        lab = gtk.Label(" - ")
        lab.show()
        hbox.pack_start(lab, 0, 0, 0)

        self.hi_limit_adj = gtk.Adjustment(25, min+1, max, 1, 10)
        hi = gtk.SpinButton(self.hi_limit_adj)
        hi.show()
        hbox.pack_start(hi, 0, 0, 0)

        refresh = gtk.Button("Go")
        refresh.show()
        refresh.connect("clicked", lambda x: self.prefill())
        hbox.pack_start(refresh, 0, 0, 0)

        def activate_go(widget):
            refresh.clicked()

        def set_hi(widget, event):
            loval = self.lo_limit_adj.get_value()
            hival = self.hi_limit_adj.get_value()
            if loval >= hival:
                self.hi_limit_adj.set_value(loval + 25)
        
        lo.connect_after("focus-out-event", set_hi)
        lo.connect_after("activate", activate_go)
        hi.connect_after("activate", activate_go)

        sep = gtk.VSeparator()
        sep.show()
        sep.set_size_request(20, -1)
        hbox.pack_start(sep, 0, 0, 0)

        showspecial = gtk.CheckButton("Special Channels")
        showspecial.connect("toggled",
                            lambda x: self.set_show_special(x.get_active()))
        showspecial.show()
        hbox.pack_start(showspecial, 0, 0, 0)

        showempty = gtk.CheckButton("Show Empty")
        showempty.set_active(self.show_empty);
        showempty.connect("toggled",
                          lambda x: self.set_show_empty(x.get_active()))
        showempty.show()
        hbox.pack_start(showempty, 0, 0, 0)

        hbox.show()

        return hbox

    def set_bank_list(self, banks):
        self.choices["Bank"].clear()
        self.choices["Bank"].append(("", "(None)"))

        i = ord("A")
        for bank in banks:
            self.choices["Bank"].append((str(bank),
                                         ("%s-%s" % (chr(i), str(bank)))))
            i += 1
        
    def set_show_special(self, show):
        self.show_special = show
        self.prefill()

    def set_show_empty(self, show):
        self.show_empty = show
        self.prefill()

    def set_read_only(self, read_only):
        self.read_only = read_only

    def __cache_columns(self):
        # We call self.col() a lot.  Caching the name->column# lookup
        # makes a significant performance improvement
        self._cached_cols = {}
        i = 0
        for x in self.cols:
            self._cached_cols[x[0]] = i
            i += 1

    def __init__(self, rthread):
        common.Editor.__init__(self)
        self.rthread = rthread
        self.allowed_bands = [144, 440]
        self.count = 100
        self.show_special = False
        self.show_empty = True

        self.read_only = False

        self.need_refresh = False

        self.lo_limit_adj = self.hi_limit_adj = None
        self.store = self.view = None

        self.__cache_columns()

        (min, max) = self.rthread.radio.get_features().memory_bounds

        self.choices["Bank"] = gtk.ListStore(TYPE_STRING, TYPE_STRING)

        job = common.RadioJob(self.set_bank_list, "get_banks")
        job.set_desc("Getting bank list")
        rthread.submit(job)

        if not self.rthread.radio.get_features()["can_odd_split"]:
            # We need a new list, so .remove() won't work for us
            self.choices["Duplex"] = [x for x in self.choices["Duplex"]
                                      if x != "split"]

        vbox = gtk.VBox(False, 2)
        vbox.pack_start(self.make_controls(min, max), 0, 0, 0)
        vbox.pack_start(self.make_editor(), 1, 1, 1)
        vbox.show()
        
        self.root = vbox

        maybe_hide = [
            ("has_bank_index", "Bank Index"),
            ("has_bank", "Bank"),
            ("has_dtcs", "DTCS Code"),
            ("has_dtcs_polarity", "DTCS Pol"),
            ("has_mode", "Mode"),
            ("has_offset", "Offset"),
            ("has_name", "Name"),
            ("has_tuning_step", "Tune Step"),
            ]
            
        for feature, colname in maybe_hide:
            supported = self.rthread.radio.get_features()[feature]
            print "%s supported: %s" % (colname, supported)
            bi = self.view.get_column(self.col(colname))
            bi.set_visible(supported)
                
        self.prefill()

        # Run low priority jobs to get the rest of the memories
        hi = int(self.hi_limit_adj.get_value())
        for i in range(hi, max+1):
            job = common.RadioJob(None, "get_memory", i)
            job.set_desc("Getting memory %i" % i)
            self.rthread.submit(job, 10)

class DstarMemoryEditor(MemoryEditor):
    def render(self, _, rend, model, iter, colnum):
        MemoryEditor.render(self, _, rend, model, iter, colnum)

        vals = model.get(iter, *tuple(range(0, len(self.cols))))
        val = vals[colnum]

        def _enabled(sensitive):
            rend.set_property("sensitive", sensitive)

        def d_unless_mode(mode):
            _enabled(vals[self.col("Mode")] == mode)

        _dv_columns = ["URCALL", "RPT1CALL", "RPT2CALL", "Digital Code"]
        dv_columns = [self.col(x) for x in _dv_columns]
        if colnum in dv_columns:
            d_unless_mode("DV")

    def _get_memory(self, iter):
        vals = self.store.get(iter, *range(0, len(self.cols)))
        if vals[self.col("Mode")] != "DV":
            return MemoryEditor._get_memory(self, iter)

        mem = chirp_common.DVMemory()

        MemoryEditor._set_mem_vals(self, mem, vals, iter)

        mem.dv_urcall = vals[self.col("URCALL")]
        mem.dv_rpt1call = vals[self.col("RPT1CALL")]
        mem.dv_rpt2call = vals[self.col("RPT2CALL")]
        mem.dv_code = vals[self.col("Digital Code")]

        return mem

    def __init__(self, rthread):
        # I think self.cols is "static" or "unbound" or something else
        # like that and += modifies the type, not self (how bizarre)
        self.cols = self.cols + \
            [("URCALL", TYPE_STRING, gtk.CellRendererCombo),
             ("RPT1CALL", TYPE_STRING, gtk.CellRendererCombo),
             ("RPT2CALL", TYPE_STRING, gtk.CellRendererCombo),
             ("Digital Code", TYPE_INT, gtk.CellRendererText),
             ]

        self.choices = dict(self.choices)
        self.defaults = dict(self.defaults)

        self.choices["URCALL"] = gtk.ListStore(TYPE_STRING, TYPE_STRING)
        self.choices["RPT1CALL"] = gtk.ListStore(TYPE_STRING, TYPE_STRING)
        self.choices["RPT2CALL"] = gtk.ListStore(TYPE_STRING, TYPE_STRING)

        self.defaults["URCALL"] = ""
        self.defaults["RPT1CALL"] = ""
        self.defaults["RPT2CALL"] = ""
        self.defaults["Digital Code"] = 0

        MemoryEditor.__init__(self, rthread)
    
        def ucall_cb(calls):
            self.defaults["URCALL"] = calls[0]
            for call in calls:
                self.choices["URCALL"].append((call, call))
        
        if self.rthread.radio.get_features().requires_call_lists:
            ujob = common.RadioJob(ucall_cb, "get_urcall_list")
            ujob.set_desc("Downloading URCALL list")
            rthread.submit(ujob)

        def rcall_cb(calls):
            self.defaults["RPT1CALL"] = calls[0]
            self.defaults["RPT2CALL"] = calls[0]
            for call in calls:
                self.choices["RPT1CALL"].append((call, call))
                self.choices["RPT2CALL"].append((call, call))

        if self.rthread.radio.get_features().requires_call_lists:
            rjob = common.RadioJob(rcall_cb, "get_repeater_call_list")
            rjob.set_desc("Downloading RPTCALL list")
            rthread.submit(rjob)

        _dv_columns = ["URCALL", "RPT1CALL", "RPT2CALL", "Digital Code"]

        if not rthread.radio.get_features().requires_call_lists:
            for i in _dv_columns:
                if not self.choices.has_key(i):
                    continue
                column = self.view.get_column(self.col(i))
                rend = column.get_cell_renderers()[0]
                rend.set_property("has-entry", True)

        for i in _dv_columns:
            col = self.view.get_column(self.col(i))
            rend = col.get_cell_renderers()[0]
            rend.set_property("family", "Monospace")

    def set_urcall_list(self, urcalls):
        store = self.choices["URCALL"]

        store.clear()
        for call in urcalls:
            store.append((call, call))

    def set_repeater_list(self, repeaters):
        for listname in ["RPT1CALL", "RPT2CALL"]:
            store = self.choices[listname]

            store.clear()
            for call in repeaters:
                store.append((call, call))

    def _set_memory(self, iter, memory):
        MemoryEditor._set_memory(self, iter, memory)

        if isinstance(memory, chirp_common.DVMemory):
            self.store.set(iter,
                           self.col("URCALL"), memory.dv_urcall,
                           self.col("RPT1CALL"), memory.dv_rpt1call,
                           self.col("RPT2CALL"), memory.dv_rpt2call,
                           self.col("Digital Code"), memory.dv_code,
                           )
        else:
            self.store.set(iter,
                           self.col("URCALL"), "",
                           self.col("RPT1CALL"), "",
                           self.col("RPT2CALL"), "",
                           self.col("Digital Code"), 0,
                           )

class ID800MemoryEditor(DstarMemoryEditor):
    pass
