// Filters project cards by category (data-tags, written by tools/tag_projects.py)
// and by origin (data-section). A chip's data-filter lists one or more values;
// a card matches a group if it has any of them. Both groups must match.
(function () {
    var chips = document.querySelectorAll(".chip[data-group]");
    var cards = document.querySelectorAll(".project[data-tags]");
    var count = document.getElementById("filter-count");
    var empty = document.getElementById("empty-note");
    var active = { tag: "", section: "" };

    function matches(values, filter) {
        if (!filter) return true;
        return filter.split(" ").some(function (f) { return values.indexOf(f) !== -1; });
    }

    function apply() {
        var shown = 0;
        cards.forEach(function (card) {
            var ok = matches(card.getAttribute("data-tags").split(" "), active.tag) &&
                matches([card.getAttribute("data-section")], active.section);
            card.classList.toggle("filtered-out", !ok);
            if (ok) shown++;
        });
        chips.forEach(function (chip) {
            var on = active[chip.getAttribute("data-group")] === chip.getAttribute("data-filter");
            chip.classList.toggle("active", on);
            chip.setAttribute("aria-pressed", on ? "true" : "false");
        });
        var filtered = active.tag || active.section;
        count.textContent = filtered ? shown + " of " + cards.length + " projects" : cards.length + " projects";
        empty.hidden = shown !== 0;
    }

    chips.forEach(function (chip) {
        chip.addEventListener("click", function () {
            active[chip.getAttribute("data-group")] = chip.getAttribute("data-filter");
            apply();
        });
    });
})();
