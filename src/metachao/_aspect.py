from inspect import getmembers, getmro, isclass

try:
    from zope.interface import classImplements
    from zope.interface import implementedBy
    ZOPE_INTERFACE_AVAILABLE = True
except ImportError:                   # pragma NO COVERAGE
    ZOPE_INTERFACE_AVAILABLE = False  # pragma NO COVERAGE

from metachao._instructions import Instruction
from metachao._instructions import overwrite
from metachao.exceptions import AspectCollision
from metachao.prototype import prototype_property
from metachao.tools import Bases, Partial, boundproperty


DICT_KEYS_OF_PLAIN_CLASS = ['__dict__', '__doc__', '__module__', '__weakref__']


# XXX: derive from list/UserList and store self on aspect?
class Instructions(object):
    """Adapter to store instructions on a aspect

    >>> class P(object): pass
    >>> instrs = Instructions(P)
    >>> instrs.append(1)
    >>> instrs.instructions
    [1]
    >>> instrs = Instructions(P)
    >>> instrs.instructions
    [1]
    """
    attrname = "__metachao_instructions__"

    @property
    def instructions(self):
        return getattr(self.aspect, self.attrname)

    def __call__(self, workbench):
        if type(workbench.origin) is AspectMeta:
            curinstr = workbench.dct[self.attrname]
            workbench.dct[self.attrname] = curinstr + self.instructions
        else:
            for instr in self.instructions:
                instr(workbench)

    def __contains__(self, name):
        for x in self:
            if x.name == name:
                return True
        else:
            return False

    def __getattr__(self, name):
        return getattr(self.instructions, name)

    # XXX: needed explicitly to make it iterable?
    def __iter__(self):
        return self.instructions.__iter__()

    def __init__(self, aspect):
        self.aspect = aspect
        if self.attrname not in aspect.__dict__:
            setattr(aspect, self.attrname, [])

    def __repr__(self):
        return repr(
            [(x.name, x.__class__, x.payload) for x in self.instructions]
            )


class Workbench(object):
    def __init__(self, origin, **kw):
        self.origin = origin
        self.kw = kw
        self.dct = dict()
        if isclass(origin):
            self.name = origin.__name__
            blacklist = DICT_KEYS_OF_PLAIN_CLASS + [
                '__metachao_origin__',
                ]
            self.dct.update(((k, v)
                             for k, v in origin.__dict__.iteritems()
                             if k not in blacklist))
            # XXX: fix naming (also see self.baseclasses)
            self.bases = Bases(origin)
            self.baseclasses = origin.__bases__
            self.type = type(origin)
            self.dct['__metachao_origin__'] = origin
        else:
            # we are pretty much creating an object that uses origin
            # as prototype.
            self.name = "Prototyper"
            self.baseclasses = ()
            self.type = type

            # bound methods found on origin, except if blacklisted
            blacklist = (
                '__class__', '__delattr__', '__doc__', '__format__',
                '__getattr__', '__getattribute__', '__hash__',
                '__init__', '__metachao_origin__',
                '__metachao_prototype__', '__new__', '__reduce__',
                '__reduce_ex__', '__repr__', '__setattr__',
                '__sizeof__', '__str__', '__subclasshook__',
                )
            self.dct.update(((k, getattr(origin, k))
                             for k, v in getmembers(origin)
                             if callable(v) and not k in blacklist))

            # properties bound to origin for all properties found on
            # origin's class
            self.dct.update(((k, prototype_property(origin, v))
                             for k, v in getmembers(origin.__class__)
                             if type(v) is property))

            # getattr fallback to origin, setattr and delattr on new
            self.dct['__getattr__'] = lambda _, name: getattr(origin, name)

            # empty __init__ needed if a later aspects plumbs it
            self.dct['__init__'] = lambda *a, **kw : None
            self.dct['__metachao_prototype__'] = origin


class AspectMeta(type):
    """meta class for aspects
    """
    def __call__(aspect, origin=None, *args, **kw):
        if kw.get('pdb'):
            import pdb;pdb.set_trace()

        # if called without positional arg, return partially applied
        # aspect
        if origin is None:
            if not kw:
                raise NeedKw
            return Partial(aspect, **kw)

        workbench = Workbench(origin, **kw)
        Instructions(aspect)(workbench)

            #raise AspectCollision(instr.name, aspect, target)

            # in case of instances functions need to be bound
            # if not x_is_class and (type(instr) is types.FunctionType):
            #     instr = instr.__get__(x)

        # build a new class, with the same name and bases as the
        # target class, but a new dictionary with the aspect applied.
        cls = workbench.type(workbench.name, workbench.baseclasses,
                             workbench.dct)
        if ZOPE_INTERFACE_AVAILABLE:
            classImplements(cls, *tuple(implementedBy(aspect)))
        if isclass(origin):
            if type(cls) is AspectMeta and kw:
                return Partial(cls, **kw)
            return cls
        return cls()

    def __init__(aspect, name, bases, dct):
        """Will be called when a aspect class is created

        Parse the aspects dictionary and generate instructions from it.
        Undecorated attributes are understood as finalize instructions.

        >>> class P(Aspect):
        ...     a = Instruction(1)
        ...     b = 2
        >>> Instructions(P)
        [('a', <class 'metachao._instructions.Instruction'>, 1),
         ('b', <class 'metachao._instructions.overwrite'>, 2)]
        """
        super(AspectMeta, aspect).__init__(name, bases, dct)

        # Get the aspect's instructions list
        instructions = Instructions(aspect)

        # walk the mro, w/o object, gathering/creating instructions
        for cls in getmro(aspect)[:-1]:
            for name, item in cls.__dict__.iteritems():
                # ignored attributes
                if name.startswith('__metachao_'):
                    continue
                if name in (
                    '__implemented__', '__metaclass__',
                    '__provides__', '__providedBy__',
                    ): continue
                if name in DICT_KEYS_OF_PLAIN_CLASS:
                    continue
                if name in instructions:
                    continue

                # XXX: rethink this
                # undecorated items are understood as overwrite
                if not isinstance(item, Instruction):
                    item = overwrite(item)
                item.__name__ = name
                item.__parent__ = aspect
                instructions.append(item)

        # # An existing docstring is an implicit plumb instruction for __doc__
        # if aspect.__doc__ is not None:
        #     instructions.append(plumb(aspect.__doc__, name='__doc__'))

        # # XXX: introduce C3 resolution
        # # check our bases for instructions we don't have already and which
        # # are not overwritten by our instructions (stage1)
        # for base in bases:
        #     # XXX: I don't like this code
        #     for instr in Instructions(base):
        #         # skip instructions we have already
        #         if instr in instructions:
        #             continue
        #         # stage1 instructions with the same name are ignored
        #         if instr.__name__ in [x.__name__ for x in instructions if
        #                 x.__stage__ == 'stage1']:
        #             continue
        #         instructions.append(instr)


class Aspect(object):
    """base class for aspects, just to set the metaclass
    """
    __metaclass__ = AspectMeta
