"""Session vendor panel for purchases, sales, and temporary buyback stock."""
import pygame

from worldforge.content.classes import EQUIPMENT_ITEMS


class VendorUI:
    TABS = ("buy", "buyback", "sell")

    def __init__(self):
        self.visible = False
        self.vendor_id = None
        self.tab = "buy"
        self.scroll = 0
        self.panel = pygame.Rect(0, 0, 0, 0)
        self.tab_rects = {}
        self.row_rects = []
        self.close_rect = pygame.Rect(0, 0, 0, 0)

    def open(self, vendor_id):
        self.visible = True
        self.vendor_id = vendor_id
        self.tab = "buy"
        self.scroll = 0

    def close(self):
        self.visible = False
        self.vendor_id = None

    def handle_event(self, event, vendor, actor_data, buyback):
        if not self.visible:
            return None
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.close()
            return None
        if event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, self.scroll - event.y)
            return None
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None
        if self.close_rect.collidepoint(event.pos):
            self.close()
            return None
        for tab, rect in self.tab_rects.items():
            if rect.collidepoint(event.pos):
                self.tab, self.scroll = tab, 0
                return None
        for rect, action in self.row_rects:
            if rect.collidepoint(event.pos):
                return action
        return None

    @staticmethod
    def _name(item):
        if item.get("name"):
            return str(item["name"])
        template_id = item.get("item_id") or item.get("template_id")
        return EQUIPMENT_ITEMS.get(template_id, {}).get(
            "name", str(template_id or "Item").replace("_", " ").title())

    def draw(self, screen, font, vendor, actor_data, buyback):
        if not self.visible or not vendor:
            return
        width, height = min(640, screen.get_width() - 32), min(540, screen.get_height() - 32)
        self.panel = pygame.Rect(0, 0, width, height)
        self.panel.center = screen.get_rect().center
        veil = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 180))
        screen.blit(veil, (0, 0))
        pygame.draw.rect(screen, (34, 39, 44), self.panel, border_radius=8)
        pygame.draw.rect(screen, (216, 192, 131), self.panel, 2, border_radius=8)
        title = vendor.get("name", "Vendor")
        screen.blit(font.render(f"{title}  ·  Gold: {actor_data.get('gold', 0)}",
                                True, (255, 230, 170)),
                    (self.panel.x + 18, self.panel.y + 14))
        small = pygame.font.Font(None, 18)
        self.close_rect = pygame.Rect(self.panel.right - 39, self.panel.y + 9, 28, 26)
        pygame.draw.rect(screen, (72, 76, 84), self.close_rect, border_radius=4)
        close_label = small.render("X", True, (250, 250, 245))
        screen.blit(close_label, close_label.get_rect(center=self.close_rect.center))

        self.tab_rects = {}
        tab_y = self.panel.y + 51
        for index, tab in enumerate(self.TABS):
            rect = pygame.Rect(self.panel.x + 18 + index * 132, tab_y, 120, 30)
            self.tab_rects[tab] = rect
            color = (94, 113, 82) if self.tab == tab else (63, 69, 77)
            pygame.draw.rect(screen, color, rect, border_radius=4)
            label = {"buy": "Buy", "buyback": f"Buyback ({len(buyback)})",
                     "sell": "Sell · 10g each"}[tab]
            rendered = small.render(label, True, (245, 245, 235))
            screen.blit(rendered, rendered.get_rect(center=rect.center))

        if self.tab == "buy":
            items = list(vendor.get("stock", []) or [])
            actions = [{"type": "vendor_buy", "vendor_id": self.vendor_id,
                        "stock_id": item.get("id")} for item in items]
            labels = [f"{self._name(item)}  ·  {int(item.get('price', 10))}g  ·  Unlimited"
                      for item in items]
        elif self.tab == "buyback":
            items = list(buyback or [])
            actions = [{"type": "vendor_buyback", "vendor_id": self.vendor_id,
                        "item_id": item.get("id")} for item in items]
            labels = [f"{self._name(item)}  ·  10g" for item in items]
        else:
            items = list(actor_data.get("inventory", []) or [])
            actions = [{"type": "vendor_sell", "vendor_id": self.vendor_id,
                        "item_id": item.get("id")} for item in items]
            labels = [f"{self._name(item)} x{max(1, int(item.get('quantity', 1)))}  ·  Sell 1 for 10g"
                      for item in items]

        row_top = tab_y + 45
        list_bottom = self.panel.bottom - 26
        row_height = 36
        visible_rows = max(1, (list_bottom - row_top) // row_height)
        self.scroll = min(self.scroll, max(0, len(items) - visible_rows))
        self.row_rects = []
        for index, (label, action) in enumerate(zip(labels, actions)):
            if index < self.scroll or index >= self.scroll + visible_rows:
                continue
            rect = pygame.Rect(self.panel.x + 18,
                               row_top + (index - self.scroll) * row_height,
                               self.panel.width - 36, 31)
            pygame.draw.rect(screen, (58, 65, 74), rect, border_radius=4)
            text = small.render(label, True, (240, 242, 244))
            screen.blit(text, (rect.x + 10, rect.y + 7))
            self.row_rects.append((rect, action))
        if not items:
            empty = "Nothing is in buyback." if self.tab == "buyback" else (
                "No items to sell." if self.tab == "sell" else "Nothing for sale.")
            screen.blit(small.render(empty, True, (195, 201, 211)),
                        (self.panel.x + 20, row_top + 8))
        screen.blit(small.render("Click an item to trade · Esc closes",
                                 True, (180, 190, 202)),
                    (self.panel.x + 18, self.panel.bottom - 22))
