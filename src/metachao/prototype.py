def prototype_property(prototype, prop):
    """prototype property

    - try fget on self, fallback to prototype
    - fset and fdel on self
    """
    def fget(self):
        try:
            return prop.fget(self)
        except AttributeError:
            return prop.fget(prototype)
    return property(fget, prop.fset, prop.fdel, prop.__doc__)
