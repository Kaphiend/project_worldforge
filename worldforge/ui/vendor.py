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
        self.pending_purchase = None
        self.quantity = 1
        self.quantity_text = "1"
        self.quantity_editing = False
        self.confirm_rects = {}
        self.quantity_slider = pygame.Rect(0, 0, 0, 0)
        self.quantity_input = pygame.Rect(0, 0, 0, 0)
        self.quantity_selectable = False

    def open(self, vendor_id):
        self.visible = True
        self.vendor_id = vendor_id
        self.tab = "buy"
        self.scroll = 0

    def close(self):
        self.visible = False
        self.vendor_id = None
        self.pending_purchase = None

    def handle_event(self, event, vendor, actor_data, buyback):
        if not self.visible:
            return None
        if self.pending_purchase:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.pending_purchase = None
                    return None
                if self.quantity_editing and self.quantity_selectable:
                    if event.key in (pygame.K_BACKSPACE, pygame.K_DELETE):
                        self.quantity_text = self.quantity_text[:-1] or "1"
                    elif event.unicode.isdigit():
                        self.quantity_text = (self.quantity_text + event.unicode)[-2:]
                    self.quantity = max(1, min(99, int(self.quantity_text or 1)))
                    self.quantity_text = str(self.quantity)
                    return None
            if event.type == pygame.MOUSEMOTION and event.buttons[0] and self.quantity_slider.collidepoint(event.pos):
                self._set_quantity_from_slider(event.pos[0])
                return None
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.confirm_rects.get("cancel", pygame.Rect(0, 0, 0, 0)).collidepoint(event.pos):
                    self.pending_purchase = None
                    return None
                if self.confirm_rects.get("confirm", pygame.Rect(0, 0, 0, 0)).collidepoint(event.pos):
                    action = dict(self.pending_purchase)
                    if action.get("type") == "vendor_buy":
                        action["quantity"] = self.quantity
                    self.pending_purchase = None
                    return action
                if self.quantity_input.collidepoint(event.pos) and self.quantity_selectable:
                    self.quantity_editing = True
                    self.quantity_text = ""
                    return None
                if self.quantity_slider.collidepoint(event.pos) and self.quantity_selectable:
                    self.quantity_editing = False
                    self._set_quantity_from_slider(event.pos[0])
                    return None
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
                if action.get("type") == "vendor_sell":
                    return action
                self.pending_purchase = action
                self.quantity = 1
                self.quantity_text = "1"
                self.quantity_editing = False
                stock = next((item for item in vendor.get("stock", []) or []
                              if item.get("id") == action.get("stock_id")), {})
                item_definition = EQUIPMENT_ITEMS.get(stock.get("item_id"), {})
                self.quantity_selectable = (action.get("type") == "vendor_buy"
                                            and bool(item_definition.get("stackable")))
                return None
        return None

    def _set_quantity_from_slider(self, x):
        if self.quantity_slider.width <= 0:
            return
        ratio = (x - self.quantity_slider.x) / self.quantity_slider.width
        self.quantity = max(1, min(99, round(1 + max(0.0, min(1.0, ratio)) * 98)))
        self.quantity_text = str(self.quantity)

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
        width, height = 640, 540
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
        if self.pending_purchase:
            veil = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            veil.fill((0, 0, 0, 175))
            screen.blit(veil, (0, 0))
            modal = pygame.Rect(0, 0, min(460, screen.get_width() - 32), 250)
            modal.center = screen.get_rect().center
            pygame.draw.rect(screen, (35, 39, 45), modal, border_radius=8)
            pygame.draw.rect(screen, (220, 194, 136), modal, 2, border_radius=8)
            stock = next((item for item in vendor.get("stock", []) or []
                          if item.get("id") == self.pending_purchase.get("stock_id")), {})
            price = max(0, int(stock.get("price", 10) or 0))
            buying = self.pending_purchase.get("type") == "vendor_buy"
            name = (self._name(stock) if buying else
                    self._name(next((item for item in buyback or []
                                    if item.get("id") == self.pending_purchase.get("item_id")), {})))
            screen.blit(small.render("Confirm purchase", True, (255, 226, 165)),
                        (modal.x + 20, modal.y + 18))
            screen.blit(small.render(name, True, (245, 245, 238)),
                        (modal.x + 20, modal.y + 54))
            stackable = buying and self.quantity_selectable
            if stackable:
                screen.blit(small.render(f"Quantity: {self.quantity}  ·  Total: {price * self.quantity} gold",
                                         True, (225, 230, 230)),
                            (modal.x + 20, modal.y + 88))
                self.quantity_input = pygame.Rect(modal.right - 86, modal.y + 82, 62, 30)
                pygame.draw.rect(screen, (55, 61, 68), self.quantity_input, border_radius=4)
                value_font = pygame.font.Font(None, 22)
                value_text = value_font.render(self.quantity_text, True, (255, 255, 245))
                screen.blit(value_text, value_text.get_rect(center=self.quantity_input.center))
                self.quantity_slider = pygame.Rect(modal.x + 22, modal.y + 134,
                                                   modal.width - 44, 12)
                pygame.draw.rect(screen, (73, 78, 86), self.quantity_slider, border_radius=6)
                knob_x = self.quantity_slider.x + int((self.quantity - 1) / 98 * self.quantity_slider.width)
                pygame.draw.circle(screen, (230, 202, 139), (knob_x, self.quantity_slider.centery), 9)
                screen.blit(small.render("1", True, (210, 215, 220)),
                            (self.quantity_slider.x, self.quantity_slider.y + 15))
                screen.blit(small.render("99", True, (210, 215, 220)),
                            (self.quantity_slider.right - 20, self.quantity_slider.y + 15))
                screen.blit(small.render("Drag the slider or click the amount to type (1–99).",
                                         True, (195, 205, 212)),
                            (modal.x + 22, modal.y + 174))
            else:
                self.quantity_input = pygame.Rect(0, 0, 0, 0)
                self.quantity_slider = pygame.Rect(0, 0, 0, 0)
                total = price if buying else 10
                screen.blit(small.render(f"Cost: {total} gold", True, (225, 230, 230)),
                            (modal.x + 20, modal.y + 92))
            cancel = pygame.Rect(modal.x + 112, modal.bottom - 46, 110, 30)
            confirm = pygame.Rect(modal.x + 238, modal.bottom - 46, 150, 30)
            pygame.draw.rect(screen, (74, 76, 80), cancel, border_radius=4)
            pygame.draw.rect(screen, (73, 119, 78), confirm, border_radius=4)
            cancel_text = small.render("Cancel", True, (250, 250, 245))
            confirm_text = small.render("Confirm purchase", True, (250, 250, 245))
            screen.blit(cancel_text, cancel_text.get_rect(center=cancel.center))
            screen.blit(confirm_text, confirm_text.get_rect(center=confirm.center))
            self.confirm_rects = {"cancel": cancel, "confirm": confirm}
