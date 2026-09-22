


class Armor:
    def __init__(self, name, base_ac, category):
        self.name = name
        self.base_ac = base_ac
        self.category = category

    def calc_ac(self, dex_mod):
        return self.base_ac + dex_mod

class LightArmor(Armor):
    def __init__(self, name, base_ac):
        super().__init__(name, base_ac, 'light')


class MediumArmor(Armor):
    def __init__(self, name, base_ac):
        super().__init__(name, base_ac, 'medium')

    def calc_a(self, dex_mod):
            return self.base_ac + min(dex_mod,2)

    
class HeavyArmor(Armor):
    def __init__(self, name, base_ac):
        super().__init__(name, base_ac, 'heavy')

    def calc_ac(self, dex_mod):
        return self.base_ac

class Unarmored(Armor):
    def __init__(self):
        super().__init__('unarmored', 10, 'unarmored')

