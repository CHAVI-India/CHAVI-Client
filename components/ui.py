"""
CHAVI Client UI component library.

All visual components for the design system. Templates live in
``components/templates/ui/<name>.html`` and use literal Tailwind class
strings (required for the PlayCDN JIT scanner).

Components are auto-discovered because this file sits inside a directory
listed in ``COMPONENTS.dirs`` (default: ``<BASE_DIR>/components/``).

Usage in templates::

    {% component "button" style="primary" size="md" icon="fas fa-save" type="submit" %}
        Save
    {% endcomponent %}

    {% component "card" %}
        {% fill "header" %}Title{% endfill %}
        {% fill "body" %}Content{% endfill %}
        {% fill "footer" %}Footer{% endfill %}
    {% endcomponent %}
"""

from django_components import Component, register


# Kwarg names that render HTML attributes. Component templates inherit the
# parent context, so an unpaginated attribute check (``{% if title %}``) would
# silently pick up a same-named context variable (e.g. a bound ``form`` or a
# ``for``-loop ``value``). Setting absent attrs to None shadows the parent.
_ATTR_KWARGS = (
    "id", "name", "value", "title", "type", "href", "target",
    "onclick", "hidden", "disabled", "form_id",
)


class KwargComponent(Component):
    """Base component that passes all kwargs to the template context.

    ``data__<name>`` kwargs are collected into a ``data`` dict which the
    templates render as ``data-<name>`` attributes::

        {% component "button" data__patient_id=patient.id %}
        -> <button ... data-patient-id="42">

    A plain ``data`` kwarg containing a dict is merged in as well.
    """

    def get_template_data(self, args, kwargs, slots, context):
        data = dict(kwargs)
        for attr in _ATTR_KWARGS:
            data.setdefault(attr, None)
        data_attrs = {
            k[6:].replace("_", "-"): v
            for k, v in kwargs.items()
            if k.startswith("data__")
        }
        merged = dict(kwargs.get("data") or {})
        merged.update(data_attrs)
        data["data"] = merged
        return data


# ---------------------------------------------------------------------------
# Core components
# ---------------------------------------------------------------------------

@register("button")
class Button(KwargComponent):
    """All buttons and button-styled links.

    Kwargs:
        style: primary|secondary|success|danger|warning|info|outline|ghost|link|
               gradient|accent|contrast|outline-dark
        size: sm|md|lg
        icon: Font Awesome class string (rendered before label)
        href: render as <a> when set (onclick/title supported on anchors)
        type: button type attribute (default "button")
        disabled: bool
        target: anchor target
        form_id: detached-form id (submits a form outside this button's ancestor)
        title, id, name, value, hidden
        data__<name>: renders data-<name> attributes (e.g. data__file_id=f.id)
        extra_class: additional CSS classes
    Slots: default (label content)
    """
    template_file = "ui/button.html"


@register("icon_button")
class IconButton(KwargComponent):
    """Icon-only action button for tables/lists.

    Kwargs:
        style: primary|danger|ghost
        size: sm|md
        icon: Font Awesome class string (required)
        aria_label: accessible label (required)
        href: render as <a> when set
        type: button type (default "button")
        disabled: bool
        title: optional tooltip
        data__<name>: renders data-<name> attributes
        extra_class: additional CSS classes
    """
    template_file = "ui/icon_button.html"


@register("card")
class Card(KwargComponent):
    """Content container.

    Kwargs: hoverable (bool), flat (bool), extra_class, id, body_class
    Slots: header, body (default), footer, actions
    """
    template_file = "ui/card.html"


@register("stat_card")
class StatCard(KwargComponent):
    """Summary metric tile: colored icon circle + big value + label.

    Kwargs: icon (FA class), style (success|danger|warning|info|accent|gray),
            value, label, sublabel
    """
    template_file = "ui/stat_card.html"


@register("table")
class Table(KwargComponent):
    """Data table wrapper.

    Kwargs: compact (bool)
    Slots: head, body (default), empty
    """
    template_file = "ui/table.html"


@register("badge")
class Badge(KwargComponent):
    """Status pill.

    Kwargs: style (success|danger|warning|info|accent|gray),
            icon (optional FA class), extra_class,
            count — renders a fixed-size count circle instead (verdigris
            when >0, gray when 0); size="sm" for w-5, default w-6
    Slots: default (badge text)
    """
    template_file = "ui/badge.html"


@register("alert")
class Alert(KwargComponent):
    """Inline alert / callout message.

    Kwargs: style (success|danger|warning|info), dismissible (bool),
            icon (optional override FA class)
    Slots: title, default (body)
    """
    template_file = "ui/alert.html"


@register("message")
class Message(KwargComponent):
    """Renders Django's ``messages`` queue as Alert components.

    Rendered once in base.html so flash messages are consumed on every
    page and cannot leak to unrelated pages.
    """
    template_file = "ui/message.html"


@register("info_box")
class InfoBox(KwargComponent):
    """Persistent instruction/tip callout (left-accent border).

    Kwargs: style (success|danger|warning|info), icon (optional override)
    Slots: title, default (body)
    """
    template_file = "ui/info_box.html"


@register("form_field")
class FormField(KwargComponent):
    """Label + widget + help text + errors wrapper.

    Kwargs: label, field_id, required (bool), help_text, errors (list|str),
            extra_class
    Slots: default (the widget markup — input/select/textarea/checkbox)
    """
    template_file = "ui/form_field.html"


@register("search_bar")
class SearchBar(KwargComponent):
    """Canonical GET search form.

    Kwargs: action, name (input name, default "q"), value, placeholder,
            method (default "get"), button_text
    """
    template_file = "ui/search_bar.html"


@register("filter_bar")
class FilterBar(KwargComponent):
    """Filter form wrapper with grid of fields + apply/clear actions.

    Kwargs: action, clear_url, method (default "get")
    Slots: fields, actions (optional override)
    """
    template_file = "ui/filter_bar.html"


@register("page_header")
class PageHeader(KwargComponent):
    """Page title block with optional back link, subtitle, actions.

    Kwargs: title, subtitle, back_url, back_text, icon
    Slots: actions
    """
    template_file = "ui/page_header.html"


@register("section_header")
class SectionHeader(KwargComponent):
    """Section title with optional icon and right-aligned actions.

    Kwargs: title, icon, icon_class
    Slots: actions, default (replaces title when provided)
    """
    template_file = "ui/section_header.html"


@register("empty_state")
class EmptyState(KwargComponent):
    """No-data placeholder.

    Kwargs: icon (default fa-inbox), title, description
    Slots: action, default (replaces description block)
    """
    template_file = "ui/empty_state.html"


@register("pagination")
class Pagination(KwargComponent):
    """Pagination controls. Expects a Django ``page_obj`` in context.

    Kwargs: page_obj, query_string, search_term (legacy → ?search=),
            elided_range, ellipsis, per_page, page_size_options,
            show_per_page (bool), total_count
    """
    template_file = "ui/pagination.html"

    def get_template_data(self, args, kwargs, slots, context):
        qs = kwargs.get("query_string") or ""
        if not qs and kwargs.get("search_term"):
            qs = "search={}".format(kwargs["search_term"])
        data = dict(kwargs)
        data["qs"] = qs
        return data


@register("back_link")
class BackLink(KwargComponent):
    """Canonical back-navigation link.

    Kwargs: href, text (default "Back")
    Slots: default (link text, overrides text kwarg)
    """
    template_file = "ui/back_link.html"


# ---------------------------------------------------------------------------
# Layout & navigation components
# ---------------------------------------------------------------------------

@register("stepper")
class Stepper(KwargComponent):
    """Wizard / multi-step progress indicator.

    Kwargs (either form):
        steps:  list of dicts {label, state}
                state = complete|active|pending
        labels: list of labels (or comma-separated string)
        current: 0-based index of the active step (steps before it are
                complete; >= len(labels) means all complete)
    """
    template_file = "ui/stepper.html"

    def get_template_data(self, args, kwargs, slots, context):
        if kwargs.get("steps"):
            computed = kwargs["steps"]
        else:
            labels = kwargs.get("labels") or ""
            if isinstance(labels, str):
                labels = [s.strip() for s in labels.split(",") if s.strip()]
            current = int(kwargs.get("current") or 0)
            computed = []
            for i, label in enumerate(labels):
                if i < current:
                    state = "complete"
                elif i == current and current < len(labels):
                    state = "active"
                elif current >= len(labels):
                    state = "complete"
                else:
                    state = "pending"
                computed.append({"label": label, "state": state})
        return {"computed_steps": computed}


@register("progress")
class Progress(KwargComponent):
    """Linear progress bar.

    Kwargs: value (0-100), label, show_percent (bool), size (sm|md|lg),
            style (primary|success|danger),
            track_id/bar_id/percent_id/label_id/bar_text_id — element ids
            for JS live-updates (Celery progress pages)
    """
    template_file = "ui/progress.html"


@register("accordion")
class Accordion(KwargComponent):
    """Collapsible panel using native <details>/<summary>.

    Kwargs: open (bool), attention (bool)
    Slots: summary, default (body)
    """
    template_file = "ui/accordion.html"


@register("data_list")
class DataList(KwargComponent):
    """Key-value metadata grid.

    Kwargs:
        items: list of dicts {label, value, style?}
        columns: 1|2|3|4 (default 4)
    """
    template_file = "ui/data_list.html"


@register("bulk_action_toolbar")
class BulkActionToolbar(KwargComponent):
    """Grouped bulk-action bar above tables.

    Slots: primary, secondary
    """
    template_file = "ui/bulk_action_toolbar.html"


@register("tabs")
class Tabs(KwargComponent):
    """Horizontal tab navigation.

    Kwargs:
        tabs: list of dicts {id, label, active, href|onclick|target}
        - href    -> anchor (page navigation)
        - onclick -> button calling a JS function
        - target  -> button calling chaviSwitchTab(target); panels use
                     data-tab-pane="<target>" to participate
    """
    template_file = "ui/tabs.html"
    js_file = "templates/ui/tabs.js"


# ---------------------------------------------------------------------------
# Interactive / data components
# ---------------------------------------------------------------------------

@register("modal")
class Modal(KwargComponent):
    """Dialog overlay.

    Kwargs: modal_id (required — unique id), danger (bool),
            size (sm|md|lg), open (render visible), close_button (bool)
    Slots: title, body (may contain a <form>), footer
    JS: open with ``openModal('<modal_id>')``, close with
        ``closeModal('<modal_id>')`` — helpers are inline in the template
        and provided once per page.
    """
    template_file = "ui/modal.html"
    js_file = "templates/ui/modal.js"


@register("dropzone")
class Dropzone(KwargComponent):
    """Drag-and-drop file upload area backed by a real file input.

    Kwargs: input_id, name, accept, help_text, icon, multiple (bool)
    """
    template_file = "ui/dropzone.html"
    js_file = "templates/ui/dropzone.js"


@register("code_block")
class CodeBlock(KwargComponent):
    """Preformatted code/JSON/UID block.

    Kwargs: variant (default|error|dark), copyable (bool), max_height
    Slots: default (code text)
    """
    template_file = "ui/code_block.html"


@register("log_feed")
class LogFeed(KwargComponent):
    """Scrolling log/timeline feed.

    Kwargs: entries — list of dicts {timestamp, type, message}
            where type = info|success|error|processing
    """
    template_file = "ui/log_feed.html"


@register("file_type_badge")
class FileTypeBadge(KwargComponent):
    """File-type icon + label, colored by extension.

    Kwargs: filename (extension is derived), label (optional override),
            show_label (bool, default True)
    """
    template_file = "ui/file_type_badge.html"

    def get_template_data(self, args, kwargs, slots, context):
        filename = (kwargs.get("filename") or "").lower()
        ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
        mapping = {
            "pdf": ("fa-file-pdf", "text-chavi-peach-600"),
            "csv": ("fa-file-excel", "text-chavi-primary-600"),
            "xlsx": ("fa-file-excel", "text-chavi-primary-600"),
            "xls": ("fa-file-excel", "text-chavi-primary-600"),
            "zip": ("fa-file-archive", "text-chavi-charcoal-600"),
            "dcm": ("fa-file-medical", "text-chavi-charcoal-600"),
            "json": ("fa-file-code", "text-chavi-charcoal-600"),
            "txt": ("fa-file-alt", "text-gray-600"),
            "md": ("fa-file-alt", "text-gray-600"),
        }
        icon, color = mapping.get(ext, ("fa-file", "text-gray-500"))
        return {
            "icon": kwargs.get("icon") or icon,
            "color": color,
            "label": kwargs.get("label") or ext.upper() or "FILE",
            "show_label": kwargs.get("show_label", True),
        }


@register("tag")
class Tag(KwargComponent):
    """Small chip/pill for multi-select values and tags.

    Kwargs: text, removable (bool), style (gray|primary)
    """
    template_file = "ui/tag.html"


@register("link_chip")
class LinkChip(KwargComponent):
    """Small inline action link for record rows (View/Add pairs).

    Kwargs: url, param, value (builds ``url?param=value``), label, icon,
            style (primary|charcoal), extra_class
    """
    template_file = "ui/link_chip.html"


def _nav_active(kwargs, context):
    """Resolve active state from ``active_on`` (comma-separated patterns
    matched against resolver_match url_name / namespace / substring)."""
    req = context.get("request")
    match = getattr(req, "resolver_match", None)
    url_name = getattr(match, "url_name", "") or ""
    namespace = getattr(match, "namespace", "") or ""
    pats = [p.strip() for p in str(kwargs.get("active_on") or "").split(",") if p.strip()]
    return bool(kwargs.get("active")) or any(
        p == url_name or p == namespace or p in url_name for p in pats
    )


@register("nav_link")
class NavLink(KwargComponent):
    """Top-level navbar link with sun active underline.

    Kwargs: href, icon, label, target, extra_class,
            active_on — comma-separated resolver_match url_name/namespace
            patterns (e.g. "taskrun" matches url_name taskrun_list)
    """
    template_file = "ui/nav_link.html"

    def get_template_data(self, args, kwargs, slots, context):
        data = super().get_template_data(args, kwargs, slots, context)
        data["active"] = _nav_active(kwargs, context)
        return data


@register("nav_dropdown")
class NavDropdown(KwargComponent):
    """Dark charcoal navbar dropdown panel (desktop nav).

    Kwargs: icon, label, active_on (comma-separated patterns, see NavLink),
            active (bool), width (default w-56)
    Slots: items — rows built with the ``nav_dropdown_item`` component.
    """
    template_file = "ui/nav_dropdown.html"

    def get_template_data(self, args, kwargs, slots, context):
        data = super().get_template_data(args, kwargs, slots, context)
        data["active"] = _nav_active(kwargs, context)
        return data


@register("nav_dropdown_item")
class NavDropdownItem(KwargComponent):
    """One row inside ``nav_dropdown`` — link or section label.

    Kwargs: href, icon, label, section (renders section header instead of link),
            divider (renders a separator row)
    """
    template_file = "ui/nav_dropdown_item.html"


@register("nav_mobile_item")
class NavMobileItem(KwargComponent):
    """One link row in the mobile nav menu.

    Kwargs: href, icon, label, section (renders section header instead of link),
            active_on (see NavLink)
    """
    template_file = "ui/nav_mobile_item.html"

    def get_template_data(self, args, kwargs, slots, context):
        data = super().get_template_data(args, kwargs, slots, context)
        data["active"] = _nav_active(kwargs, context)
        return data


@register("loading_overlay")
class LoadingOverlay(KwargComponent):
    """Full-area spinner overlay; toggle with hidden/flex like modal.

    Kwargs: id (JS target), label (default "Loading…")
    """
    template_file = "ui/loading_overlay.html"


@register("stat_tile")
class StatTile(KwargComponent):
    """Dashboard metric tile: label top, value + corner icon bottom row.

    Kwargs: label, value, icon, icon_style (primary|sand|sun|charcoal|peach),
            href (optional — renders as <a>)
    """
    template_file = "ui/stat_tile.html"


@register("action_tile")
class ActionTile(KwargComponent):
    """Icon tile + title + description link card.

    Kwargs: href, icon, icon_style (primary|sand|sun|charcoal|peach), title
    Slots: default (description)
    """
    template_file = "ui/action_tile.html"


@register("feature_tile")
class FeatureTile(KwargComponent):
    """Tinted capability tile for bento grids.

    Kwargs: accent (primary|sand|sun|charcoal|peach), icon, title,
            span (grid classes), large (bool), extra_class
    Slots: default (body copy)
    """
    template_file = "ui/feature_tile.html"


@register("notification_dropdown")
class NotificationDropdown(KwargComponent):
    """Notification bell + dropdown (extracted from base.html).

    Kwargs: notifications — list of dicts {message, url, created_at, unread}
    """
    template_file = "ui/notification_dropdown.html"
