import re
import os
from AppKit import *
from Foundation import *
from subprocess import Popen, PIPE
from nodebox import bundle_path

def get_default(label, packed=False):
    if not label.startswith('NS'):
        label = 'nodebox:%s'%label
    pref = NSUserDefaults.standardUserDefaults().objectForKey_(label)
    return pref if not packed else unpackAttrs(pref)

def set_default(label, value, packed=False):
    if not label.startswith('NS'):
        label = 'nodebox:%s'%label    
    value = value if not packed else packAttrs(value)
    NSUserDefaults.standardUserDefaults().setObject_forKey_(value, label)

FG_COLOR = NSForegroundColorAttributeName
BG_COLOR = NSBackgroundColorAttributeName

def unpackAttrs(d):
    unpacked = {}
    for key, value in d.items():
        if key == NSFontAttributeName:
            value = NSFont.fontWithName_size_(value['name'], value['size'])
        elif key in (FG_COLOR, BG_COLOR):
            r, g, b, a = map(float, value.split())
            value = NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)
        elif isinstance(value, (dict, NSDictionary)):
            value = unpackAttrs(value)
        unpacked[key] = value
    return unpacked

def packAttrs(d):
    packed = {}
    for key, value in d.items():
        if key == NSFontAttributeName:
            value = {"name": value.fontName(), "size": value.pointSize()}
        elif key in (FG_COLOR, BG_COLOR):
            channels = value.colorUsingColorSpaceName_(NSCalibratedRGBColorSpace).getRed_green_blue_alpha_(None, None, None, None)
            value = " ".join(map(str, channels))
            packed = {key:value}
            break
        elif isinstance(value, (dict, NSDictionary)):
            value = packAttrs(value)
        packed[key] = value
    return packed

def getBasicTextAttributes():
    return get_default("text-attributes", packed=True)

def getSyntaxTextAttributes():
    syntax = {}
    basic = get_default("text-attributes", packed=True)
    for fontname,attrs in get_default("text-colors", packed=True).items():
        syntax[fontname] = dict(attrs.items()+basic.items())
    return syntax

def setBasicTextAttributes(basicAttrs):
    if basicAttrs != getBasicTextAttributes():
        set_default("text-attributes", basicAttrs, packed=True)
        nc = NSNotificationCenter.defaultCenter()
        nc.postNotificationName_object_("PyDETextFontChanged", None)

def setSyntaxTextAttributes(syntaxAttrs):
    if syntaxAttrs != getSyntaxTextAttributes():
        set_default("text-colors", syntaxAttrs, packed=True)
        nc = NSNotificationCenter.defaultCenter()
        nc.postNotificationName_object_("PyDETextFontChanged", None)

def setTextFont(font):
    basicAttrs = getBasicTextAttributes()
    syntaxAttrs = getSyntaxTextAttributes()
    basicAttrs[NSFontAttributeName] = font
    for v in syntaxAttrs.values():
        v[NSFontAttributeName] = font
    setBasicTextAttributes(basicAttrs)
    setSyntaxTextAttributes(syntaxAttrs)

def possibleToolLocations():
    homebin = '%s/bin/nodebox'%os.environ['HOME']
    localbin = '/usr/local/bin/nodebox'
    locations = [homebin, localbin]

    # find the user's path by launching the same shell Terminal.app uses
    # and peeking at the $PATH
    term = NSUserDefaults.standardUserDefaults().persistentDomainForName_('com.apple.Terminal')
    if term:
        setting = term['Default Window Settings']
        shell = term['Window Settings'][setting]['CommandString']
        p = Popen([shell,"-l"], stdout=PIPE, stderr=PIPE, stdin=PIPE)
        out, err = p.communicate("echo $PATH")
        for path in out.strip().split(':'):
            path += '/nodebox'
            if '/sbin' in path: continue
            if path.startswith('/bin'): continue
            if path.startswith('/usr/bin'): continue
            if path in locations: continue
            locations.append(path)
    return locations

# class defined in NodeBoxPreferences.xib
class NodeBoxPreferencesController(NSWindowController):
    fontPreview = objc.IBOutlet()
    keepWindows = objc.IBOutlet()
    toolInstall = objc.IBOutlet()
    toolPath = objc.IBOutlet()
    toolRepair = objc.IBOutlet()
    toolInstallSheet = objc.IBOutlet()
    toolInstallMenu = objc.IBOutlet()
    toolPort = objc.IBOutlet()
    toolPortLabel = objc.IBOutlet()
    toolPortStepper = objc.IBOutlet()
    toolPortTimer = None
    commentsColorWell = objc.IBOutlet()
    funcClassColorWell = objc.IBOutlet()
    keywordsColorWell = objc.IBOutlet()
    stringsColorWell = objc.IBOutlet()
    plainColorWell = objc.IBOutlet()
    errColorWell = objc.IBOutlet()
    pageColorWell = objc.IBOutlet()
    selectionColorWell = objc.IBOutlet()
    # toolFound = False
    # toolValid = False

    def init(self):
        self = self.initWithWindowNibName_("NodeBoxPreferences")
        self.setWindowFrameAutosaveName_("NodeBoxPreferencesPanel")
        self.timer = None
        return self

    def awakeFromNib(self):
        self.textFontChanged_(None)
        syntaxAttrs = getSyntaxTextAttributes()
        self.stringsColorWell.setColor_(syntaxAttrs["string"][FG_COLOR])
        self.keywordsColorWell.setColor_(syntaxAttrs["keyword"][FG_COLOR])
        self.funcClassColorWell.setColor_(syntaxAttrs["identifier"][FG_COLOR])
        self.commentsColorWell.setColor_(syntaxAttrs["comment"][FG_COLOR])
        self.plainColorWell.setColor_(syntaxAttrs["plain"][FG_COLOR])
        self.errColorWell.setColor_(syntaxAttrs["err"][FG_COLOR])
        self.pageColorWell.setColor_(syntaxAttrs["page"][BG_COLOR])
        self.selectionColorWell.setColor_(syntaxAttrs["selection"][BG_COLOR])
        self._wells = [self.commentsColorWell, self.funcClassColorWell, self.keywordsColorWell, self.stringsColorWell, self.plainColorWell, self.errColorWell, self.pageColorWell, self.selectionColorWell]
        self.toolPortStepper.setIntValue_(get_default('remote-port'))
        self.toolPort.setStringValue_(str(get_default('remote-port')))
        self.toolPort.setTextColor_(ERR_COL if not NSApp().delegate()._listener.active else NSColor.blackColor())
        nc = NSNotificationCenter.defaultCenter()
        nc.addObserver_selector_name_object_(self, "textFontChanged:", "PyDETextFontChanged", None)
        nc.addObserver_selector_name_object_(self, "blur:", "NSWindowDidResignKeyNotification", None)
        self.checkTool()

    def windowWillClose_(self, notification):
        fm = NSFontManager.sharedFontManager()
        fp = fm.fontPanel_(False)
        if fp is not None:
            fp.setDelegate_(None)
            fp.close()

    def windowDidBecomeMain_(self, notification):
        self.checkTool()

    def controlTextDidChange_(self, note):
        print note.userInfo
        txt = re.sub(r'[^0-9]','', self.toolPort.stringValue())
        print "changed",txt
        self.toolPort.setStringValue_("huh?")

    @objc.IBAction
    def updateColors_(self, sender):
        if not self.timer:
            self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                                    0.2, self, "timeToUpdateTheColors:", None, True)

    def checkTool(self):
        broken = []
        for path in possibleToolLocations():
            if os.path.islink(path):
                # if it's a symlink, make sure it points to this bundle
                tool_path = os.path.realpath(path)
                found = path
                valid = tool_path.startswith(bundle_path())
                if valid: break
                broken.append(path)
            if os.path.exists(path):
                # if it's a normal file, something went wrong
                broken.append(path)
        else:
            # didn't find any working symlinks in the $PATH
            found = broken[0] if broken else None
            valid = False

        self.toolInstall.setHidden_(found is not None)
        self.toolPath.setSelectable_(found is not None)
        # self.toolPath.setStringValue_(found.replace(os.environ['HOME'],'~') if found else '')
        self.toolPath.setStringValue_(found if found else '')
        self.toolPath.setTextColor_(ERR_COL if not valid else NSColor.blackColor())
        self.toolRepair.setHidden_(not (found and not valid) )
        self.toolPort.setHidden_(not valid)
        self.toolPortLabel.setHidden_(not valid)
        self.toolPortStepper.setHidden_(not valid)
        if valid: set_default('remote-port', get_default('remote-port'))

    @objc.IBAction
    def modifyPort_(self, sender):
        newport = sender.intValue()
        self.toolPort.setStringValue_(str(newport))

        if self.toolPortTimer:
            self.toolPortTimer.invalidate()
        self.toolPortTimer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.4, self, "switchPort:", None, False)

    def switchPort_(self, timer):
        newport = self.toolPortStepper.intValue()
        set_default('remote-port', newport)
        app = NSApp().delegate()
        app.listenOnPort_(newport)
        self.toolPort.setTextColor_(ERR_COL if not app._listener.active else NSColor.blackColor())
        self.toolPortTimer = None

    @objc.IBAction 
    def installTool_(self, sender):
        locs = [loc.replace(os.environ['HOME'],'~') for loc in possibleToolLocations()]
        self.toolInstallMenu.removeAllItems()
        self.toolInstallMenu.addItemsWithTitles_(locs)
        NSApp().beginSheet_modalForWindow_modalDelegate_didEndSelector_contextInfo_(self.toolInstallSheet, self.window(), self, None, 0)

    @objc.IBAction
    def finishInstallation_(self, sender):
        should_install = sender.tag()
        if should_install:
            console_py = bundle_path('Contents/SharedSupport/nodebox')
            pth = self.toolInstallMenu.selectedItem().title().replace('~',os.environ['HOME'])
            dirname = os.path.dirname(pth)
            try:
                if os.path.exists(pth) or os.path.islink(pth):
                    os.unlink(pth)
                elif not os.path.exists(dirname):
                    os.makedirs(dirname)
                os.symlink(console_py, pth)
            except OSError:
                Installer = objc.lookUpClass('Installer')
                Installer.createLink_(pth)
        self.checkTool()
        NSApp().endSheet_(self.toolInstallSheet)
        self.toolInstallSheet.orderOut_(self)

    def timeToUpdateTheColors_(self, sender):
        syntaxAttrs = getSyntaxTextAttributes()
        syntaxAttrs["string"][FG_COLOR] = self.stringsColorWell.color()
        syntaxAttrs["keyword"][FG_COLOR] = self.keywordsColorWell.color()
        syntaxAttrs["identifier"][FG_COLOR] = self.funcClassColorWell.color()
        syntaxAttrs["comment"][FG_COLOR] = self.commentsColorWell.color()
        syntaxAttrs["plain"][FG_COLOR] = self.plainColorWell.color()
        syntaxAttrs["err"][FG_COLOR] = self.errColorWell.color()
        syntaxAttrs["page"][BG_COLOR] = self.pageColorWell.color()
        syntaxAttrs["selection"][BG_COLOR] = self.selectionColorWell.color()
        setSyntaxTextAttributes(syntaxAttrs)
        active = [w for w in self._wells if w.isActive()]
        if not active:
            self.stopUpdating()

    def stopUpdating(self):
        if self.timer:
            self.timer.invalidate()
            self.timer = None

    @objc.IBAction
    def chooseFont_(self, sender):
        fm = NSFontManager.sharedFontManager()
        basicAttrs = get_default("text-attributes", packed=True)
        fm.setSelectedFont_isMultiple_(basicAttrs[NSFontAttributeName], False)
        fm.orderFrontFontPanel_(sender)
        fp = fm.fontPanel_(False)
        fp.setDelegate_(self)

    @objc.IBAction
    def changeFont_(self, sender):
        oldFont = get_default("text-attributes", packed=True)[NSFontAttributeName]
        newFont = sender.convertFont_(oldFont)
        if oldFont != newFont:
            setTextFont(newFont)
    
    def blur_(self, note):
        self.stopUpdating()
        for well in [w for w in self._wells if w.isActive()]:
            well.deactivate()
        NSColorPanel.sharedColorPanel().orderOut_(objc.nil)

    def textFontChanged_(self, notification):
        basicAttrs = get_default("text-attributes", packed=True)
        font = basicAttrs[NSFontAttributeName]
        self.fontPreview.setFont_(font)
        size = font.pointSize()
        if size == int(size):
            size = int(size)
        s = u"%s %s" % (font.displayName(), size)
        self.fontPreview.setStringValue_(s)

    def __del__(self):
        self.stopUpdating()
        nc = NSNotificationCenter.defaultCenter()
        nc.removeObserver_name_object_(self, "PyDETextFontChanged", None)
        nc.removeObserver_name_object_(self, "NSWindowDidResignKeyNotification", None)

ERR_COL = NSColor.colorWithRed_green_blue_alpha_(167/255.0, 41/255.0, 34/255.0, 1.0)
def defaultDefaults():
    _basicFont = NSFont.userFixedPitchFontOfSize_(11)
    _BASICATTRS = {NSFontAttributeName: _basicFont,
                   NSLigatureAttributeName: 0}
    _LIGHT_SYNTAXCOLORS = {
        # text colors
        "keyword": {FG_COLOR: NSColor.colorWithRed_green_blue_alpha_(0.7287307382, 0.2822835445, 0.01825759932, 1.0)},
        "identifier": {FG_COLOR: NSColor.colorWithRed_green_blue_alpha_(0.0636304393411, 0.506952047348, 0.661560952663, 1.0)},
        "string": {FG_COLOR: NSColor.colorWithRed_green_blue_alpha_(0.0979111269116, 0.482684463263, 0.00660359347239, 1.0)},
        "comment": {FG_COLOR: NSColor.colorWithRed_green_blue_alpha_(0.391519248486, 0.391507565975, 0.391514211893, 1.0)},
        "plain": {FG_COLOR: NSColor.blackColor()},
        "err": {FG_COLOR: ERR_COL},
        # background colors
        "page": {BG_COLOR: NSColor.whiteColor()},
        "selection": {BG_COLOR: NSColor.colorWithRed_green_blue_alpha_(0.743757605553, 0.976963877678, 0.998794317245, 1.0)},
    }

    _DARK_SYNTAXCOLORS = {
        # text colors
        "identifier":{FG_COLOR:NSColor.colorWithRed_green_blue_alpha_(0.72914814949, 0.171053349972, 0.106676459312, 1.0)},
        "constant":{FG_COLOR:NSColor.colorWithRed_green_blue_alpha_(0.0636304393411, 0.506952047348, 0.661560952663, 1.0)},
        "keyword":{FG_COLOR:NSColor.colorWithRed_green_blue_alpha_(243/255.0, 192/255.0, 36/255.0, 1.0)},
        "string":{FG_COLOR:NSColor.colorWithRed_green_blue_alpha_(0.132785454392, 0.560580074787, 0.0322014801204, 1.0)},
        "comment":{FG_COLOR:NSColor.colorWithRed_green_blue_alpha_(0.43789768219, 0.497855067253, 0.612316548824, 1.0)},
        "plain":{FG_COLOR:NSColor.colorWithRed_green_blue_alpha_(0.789115667343, 0.843085050583, 0.837674379349, 1.0)},
        "err":{FG_COLOR:NSColor.colorWithRed_green_blue_alpha_(0.664596498013, 0.0, 0.0132505837828, 1.0)},
        # background colors
        "page":{BG_COLOR:NSColor.colorWithRed_green_blue_alpha_(0.0436993055046, 0.0851569622755, 0.146313145757, 1.0)},
        "selection":{BG_COLOR:NSColor.colorWithRed_green_blue_alpha_(0.19904075563, 0.230226844549, 0.373898953199, 1.0)},

    }
    

    _SYNTAXCOLORS = _DARK_SYNTAXCOLORS

    for key, value in _SYNTAXCOLORS.items():
        newVal = _BASICATTRS.copy()
        newVal.update(value)
        _SYNTAXCOLORS[key] = NSDictionary.dictionaryWithDictionary_(newVal)
    _BASICATTRS = NSDictionary.dictionaryWithDictionary_(_BASICATTRS)

    return {
        # "NSQuitAlwaysKeepsWindows": True,
        "nodebox:remote-port": 9001,
        "nodebox:text-attributes": packAttrs(_BASICATTRS),
        "nodebox:text-colors": packAttrs(_SYNTAXCOLORS),
    }
NSUserDefaults.standardUserDefaults().registerDefaults_(defaultDefaults())
