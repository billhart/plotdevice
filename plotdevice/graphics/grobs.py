# encoding: utf-8
import os
import re
import json
import warnings
import math
from contextlib import contextmanager
from AppKit import *
from Foundation import *
from Quartz import *

from plotdevice import DeviceError
from ..util import _copy_attr, _copy_attrs, _flatten, trim_zeroes
from ..lib import geometry
from .colors import Color
from .effects import Effect

_ctx = None
__all__ = [
        "DEFAULT_WIDTH", "DEFAULT_HEIGHT",
        "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT", "KEY_BACKSPACE", "KEY_TAB", "KEY_ESC",
        "COPY", "LIVE", "OFF",
        "Variable", "NUMBER", "TEXT", "BOOLEAN","BUTTON",
        "Grob", "Image",
        ]

DEFAULT_WIDTH, DEFAULT_HEIGHT = 512, 512
INHERIT = "inherit"

# plotstyle mode
COPY = "copy"
LIVE = "live"
OFF = "off"

# var datatypes
NUMBER = 1
TEXT = 2
BOOLEAN = 3
BUTTON = 4

# ui events
KEY_UP = 126
KEY_DOWN = 125
KEY_LEFT = 123
KEY_RIGHT = 124
KEY_BACKSPACE = 51
KEY_TAB = 48
KEY_ESC = 53


def _save():
    NSGraphicsContext.currentContext().saveGraphicsState()

def _restore():
    NSGraphicsContext.currentContext().restoreGraphicsState()

### Grobs & mixins to inherit state from the context ###

class Grob(object):
    """A GRaphic OBject is the base class for all drawing primitives."""

    def __init__(self, **kwargs):
        attr_tuples = [getattr(cls,'stateAttrs',tuple()) for cls in self.__class__.__mro__]
        self.stateAttrs = sum(attr_tuples, tuple())

    def draw(self):
        """Appends a copy of the grob to the canvas.
           This will result in a _draw later on, when the scene graph is rendered."""
        if _ctx.plotstyle is OFF:
            return
        grob = self.copy() if _ctx._plotstyle is COPY else self
        grob.inherit()
        _ctx.canvas.append(grob)

    def copy(self):
        """Returns a deep copy of this grob."""
        raise NotImplementedError, "Copy is not implemented on this Grob class."

    def inherit(self):
        """Fills in unspecified attributes with the graphics context's state"""
        attrs_to_copy = [a for a in self.stateAttrs if getattr(self, a, INHERIT) is INHERIT]
        _copy_attrs(_ctx, self, attrs_to_copy)

    @classmethod
    def validate(self, kwargs):
        """Sanity check a potential set of constructor kwargs"""
        remaining = [arg for arg in kwargs.keys() if arg not in self.kwargs]
        if remaining:
            unknown = "Unknown argument(s) '%s'" % ", ".join(remaining)
            raise DeviceError(unknown)

class EffectsMixin(Grob):
    """Mixin class for transparency layer support.
    Adds the alpha, blend, and shadow attributes to the class."""
    stateAttrs = ('_effects',)

    def __init__(self, **kwargs):
        super(EffectsMixin, self).__init__(**kwargs)
        self._effects = INHERIT # effects from the context
        self._solo_fx = {}      # effect overrides from inline kwargs
        for eff, val in {k:kwargs[k] for k in kwargs if k in Effect.kwargs}.items():
            setattr(self, eff, val)

    @property
    def effects(self):
        """An Effect object merging inherited alpha/blend/shadow with local overrides"""
        merged = Effect() if self._effects==INHERIT else self._effects
        if self._solo_fx:
            merged = Effect(merged, **self._solo_fx)
        return merged

    def _get_alpha(self):
        return self._solo_fx.get('alpha', _ctx._effects.alpha)
    def _set_alpha(self, a):
        self._solo_fx['alpha'] = Effect._validate('alpha',a)
    alpha = property(_get_alpha, _set_alpha)

    def _get_blend(self):
        return self._solo_fx.get('blend', _ctx._effects.blend)
    def _set_blend(self, mode):
        self._solo_fx['blend'] = Effect._validate('blend', mode)
    blend = property(_get_blend, _set_blend)

    def _get_shadow(self):
        return self._solo_fx.get('shadow', _ctx._effects.shadow)
    def _set_shadow(self, spec):
        self._solo_fx['shadow'] = Effect._validate('shadow', spec)
    shadow = property(_get_shadow, _set_shadow)

class ColorMixin(Grob):
    """Mixin class for color support.
    Adds the _fillcolor and _strokecolor attributes to the class."""
    stateAttrs = ('_fillcolor', '_strokecolor')

    def __init__(self, **kwargs):
        super(ColorMixin, self).__init__(**kwargs)
        try:
            self._fillcolor = Color(kwargs['fill'])
        except KeyError:
            self._fillcolor = INHERIT
        try:
            self._strokecolor = Color(kwargs['stroke'])
        except KeyError:
            self._strokecolor = INHERIT

    def _get_fill(self):
        return _ctx._fillcolor if self._fillcolor is INHERIT else self._fillcolor
    def _set_fill(self, *args):
        self._fillcolor = Color(*args)
    fill = property(_get_fill, _set_fill)

    def _get_stroke(self):
        return _ctx._strokecolor if self._strokecolor is INHERIT else self._strokecolor
    def _set_stroke(self, *args):
        self._strokecolor = Color(*args)
    stroke = property(_get_stroke, _set_stroke)

class TransformMixin(Grob):
    """Mixin class for transformation support.
    Adds the _transform and _transformmode attributes to the class."""
    stateAttrs = ('_transform', '_transformmode')

    def __init__(self, **kwargs):
        super(TransformMixin, self).__init__(**kwargs)
        self._reset()

    def _reset(self):
        self._transform = INHERIT
        self._transformmode = INHERIT

    def _get_transform(self):
        return self._transform if self._transform!=INHERIT else _ctx._transform
    def _set_transform(self, transform):
        self._transform = Transform(transform)
    transform = property(_get_transform, _set_transform)

    def _get_transformmode(self):
        return self._transformmode if self._transformmode!=INHERIT else _ctx._transformmode
    def _set_transformmode(self, mode):
        self._transformmode = mode
    transformmode = property(_get_transformmode, _set_transformmode)

    def translate(self, x, y):
        self._transform.translate(x, y)

    def reset(self):
        self._transform = Transform()

    def rotate(self, degrees=0, radians=0):
        self._transform.rotate(-degrees,-radians)

    def translate(self, x=0, y=0):
        self._transform.translate(x,y)

    def scale(self, x=1, y=None):
        self._transform.scale(x,y)

    def skew(self, x=0, y=0):
        self._transform.skew(x,y)

class PenMixin(Grob):
    stateAttrs = ('_strokewidth', '_capstyle', '_joinstyle', '_dashstyle')

    """Mixin class for linestyle support.
    Adds the _capstyle, _joinstyle, _dashstyle, and _strokewidth attributes to the class."""

    def __init__(self, **kwargs):
        super(PenMixin, self).__init__(**kwargs)
        self.strokewidth = kwargs.get('nib', kwargs.get('strokewidth', INHERIT))
        self.capstyle = kwargs.get('cap', kwargs.get('capstyle', INHERIT))
        self.joinstyle = kwargs.get('join', kwargs.get('joinstyle', INHERIT))
        self.dashstyle = kwargs.get('dash', kwargs.get('dashstyle', INHERIT))

    def _get_strokewidth(self):
        return _ctx._strokewidth if self._strokewidth is INHERIT else self._strokewidth
    def _set_strokewidth(self, strokewidth):
        self._strokewidth = max(strokewidth, 0.0001)
    nib = strokewidth = property(_get_strokewidth, _set_strokewidth)

    def _get_capstyle(self):
        return _ctx._capstyle if self._capstyle is INHERIT else self._capstyle
    def _set_capstyle(self, style):
        from bezier import BUTT, ROUND, SQUARE
        if style not in (INHERIT, BUTT, ROUND, SQUARE):
            badstyle = 'Line cap style should be BUTT, ROUND or SQUARE.'
            raise DeviceError(badstyle)
        self._capstyle = style
    cap = capstyle = property(_get_capstyle, _set_capstyle)

    def _get_joinstyle(self):
        return _ctx._joinstyle if self._joinstyle is INHERIT else self._joinstyle
    def _set_joinstyle(self, style):
        from bezier import MITER, ROUND, BEVEL
        if style not in (INHERIT, MITER, ROUND, BEVEL):
            badstyle = 'Line join style should be MITER, ROUND or BEVEL.'
            raise DeviceError(badstyle)
        self._joinstyle = style
    join = joinstyle = property(_get_joinstyle, _set_joinstyle)

    def _get_dashstyle(self):
        return _ctx._dashstyle if self._dashstyle is INHERIT else self._dashstyle
    def _set_dashstyle(self, *segments):
        if None in segments or INHERIT in segments:
            self._dashstyle = segments[0]
        else:
            steps = map(int, _flatten(segments))
            if len(steps)%2:
                steps += steps[-1:] # assume even spacing for omitted skip sizes
            self._dashstyle = steps
    dash = dashstyle = property(_get_dashstyle, _set_dashstyle)


### Images ###

class Image(TransformMixin):
    kwargs = ()

    def __init__(self, path=None, x=0, y=0, width=None, height=None, alpha=1.0, image=None, data=None):
        """
        Parameters:
         - path: A path to a certain image on the local filesystem.
         - x: Horizontal position.
         - y: Vertical position.
         - width: Maximum width. Images get scaled according to this factor.
         - height: Maximum height. Images get scaled according to this factor.
              If a width and height are both given, the smallest
              of the two is chosen.
         - alpha: transparency factor
         - image: optionally, an Image or NSImage object.
         - data: a stream of bytes of image data.
        """
        super(Image, self).__init__()
        if data is not None:
            if not isinstance(data, NSData):
                data = NSData.dataWithBytes_length_(data, len(data))
            self._nsImage = NSImage.alloc().initWithData_(data)
            if self._nsImage is None:
                unreadable = "can't read image %r" % path
                raise DeviceError(unreadable)
            self._nsImage.setFlipped_(True)
            self._nsImage.setCacheMode_(NSImageCacheNever)
        elif image is not None:
            if isinstance(image, NSImage):
                self._nsImage = image
                self._nsImage.setFlipped_(True)
            else:
                wrongtype = "Don't know what to do with %s." % image
                raise DeviceError(wrongtype)
        elif path is not None:
            if not os.path.exists(path):
                notfound = 'Image "%s" not found.' % path
                raise DeviceError(notfound)
            curtime = os.path.getmtime(path)
            try:
                image, lasttime = _ctx._imagecache[path]
                if lasttime != curtime:
                    image = None
            except KeyError:
                pass
            if image is None:
                image = NSImage.alloc().initWithContentsOfFile_(path)
                if image is None:
                    invalid = "Can't read image %r" % path
                    raise DeviceError(invalid)
                image.setFlipped_(True)
                image.setCacheMode_(NSImageCacheNever)
                _ctx._imagecache[path] = (image, curtime)
            self._nsImage = image
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.alpha = alpha
        self.debugImage = False

    @property
    def image(self):
        warnings.warn("The 'image' attribute is deprecated. Please use _nsImage instead.", DeprecationWarning, stacklevel=2)
        return self._nsImage

    def copy(self):
        new = self.__class__()
        _copy_attrs(self, new, ('_nsImage', 'x', 'y', 'width', 'height', '_transform', '_transformmode', 'alpha', 'debugImage'))
        return new

    def getSize(self):
        return Size(*self._nsImage.size())

    size = property(getSize)

    def _draw(self):
        """Draw an image on the given coordinates."""

        srcW, srcH = self._nsImage.size()
        srcRect = ((0, 0), (srcW, srcH))

        # Width or height given
        if self.width is not None or self.height is not None:
            if self.width is not None and self.height is not None:
                factor = min(self.width / srcW, self.height / srcH)
            elif self.width is not None:
                factor = self.width / srcW
            elif self.height is not None:
                factor = self.height / srcH
            _save()

            # Center-mode transforms: translate to image center
            if self._transformmode == CENTER:
                # This is the hardest case: center-mode transformations with given width or height.
                # Order is very important in this code.

                # Set the position first, before any of the scaling or transformations are done.
                # Context transformations might change the translation, and we don't want that.
                t = Transform()
                t.translate(self.x, self.y)
                t.concat()

                # Set new width and height factors. Note that no scaling is done yet: they're just here
                # to set the new center of the image according to the scaling factors.
                srcW = srcW * factor
                srcH = srcH * factor

                # Move image to newly calculated center.
                dX = srcW / 2
                dY = srcH / 2
                t = Transform()
                t.translate(dX, dY)
                t.concat()

                # Do current transformation.
                self._transform.concat()

                # Move back to the previous position.
                t = Transform()
                t.translate(-dX, -dY)
                t.concat()

                # Finally, scale the image according to the factors.
                t = Transform()
                t.scale(factor)
                t.concat()
            else:
                # Do current transformation
                self._transform.concat()
                # Scale according to width or height factor
                t = Transform()
                t.translate(self.x, self.y) # Here we add the positioning of the image.
                t.scale(factor)
                t.concat()

            # A debugImage draws a black rectangle instead of an image.
            if self.debugImage:
                Color().set()
                pt = Bezier()
                pt.rect(0, 0, srcW / factor, srcH / factor)
                pt.fill()
            else:
                self._nsImage.drawAtPoint_fromRect_operation_fraction_((0, 0), srcRect, NSCompositeSourceOver, self.alpha)
            _restore()
        # No width or height given
        else:
            _save()
            x,y = self.x, self.y
            # Center-mode transforms: translate to image center
            if self._transformmode == CENTER:
                deltaX = srcW / 2
                deltaY = srcH / 2
                t = Transform()
                t.translate(x+deltaX, y+deltaY)
                t.concat()
                x = -deltaX
                y = -deltaY
            # Do current transformation
            self._transform.concat()
            # A debugImage draws a black rectangle instead of an image.
            if self.debugImage:
                Color().set()
                pt = Bezier()
                pt.rect(x, y, srcW, srcH)
                pt.fill()
            else:
                # The following code avoids a nasty bug in Cocoa/PyObjC.
                # Apparently, EPS files are put on a different position when drawn with a certain position.
                # However, this only happens when the alpha value is set to 1.0: set it to something lower
                # and the positioning is the same as a bitmap file.
                # I could of course make every EPS image have an alpha value of 0.9999, but this solution
                # is better: always use zero coordinates for drawAtPoint and use a transform to set the
                # final position.
                t = Transform()
                t.translate(x,y)
                t.concat()
                self._nsImage.drawAtPoint_fromRect_operation_fraction_((0,0), srcRect, NSCompositeSourceOver, self.alpha)
            _restore()


class Variable(object):
    def __init__(self, name, type, default=None, min=0, max=100, value=None):
        self.name = name
        self.type = type or NUMBER
        if self.type == NUMBER:
            if default is None:
                self.default = 50
            else:
                self.default = default
            self.min = min
            self.max = max
        elif self.type == TEXT:
            if default is None:
                self.default = "hello"
            else:
                self.default = default
        elif self.type == BOOLEAN:
            if default is None:
                self.default = True
            else:
                self.default = default
        elif self.type == BUTTON:
            self.default = self.name
        self.value = value or self.default

    def sanitize(self, val):
        """Given a Variable and a value, cleans it out"""
        if self.type == NUMBER:
            try:
                return float(val)
            except ValueError:
                return 0.0
        elif self.type == TEXT:
            return unicode(str(val), "utf_8", "replace")
            try:
                return unicode(str(val), "utf_8", "replace")
            except:
                return ""
        elif self.type == BOOLEAN:
            if unicode(val).lower() in ("true", "1", "yes"):
                return True
            else:
                return False

    def compliesTo(self, v):
        """Return whether I am compatible with the given var:
             - Type should be the same
             - My value should be inside the given vars' min/max range.
        """
        if self.type == v.type:
            if self.type == NUMBER:
                if self.value < self.min or self.value > self.max:
                    return False
            return True
        return False

    @trim_zeroes
    def __repr__(self):
        return "Variable(name=%s, type=%s, default=%s, min=%s, max=%s, value=%s)" % (self.name, self.type, self.default, self.min, self.max, self.value)


def _test():
    import doctest, cocoa
    return doctest.testmod(cocoa)

if __name__=='__main__':
    _test()
