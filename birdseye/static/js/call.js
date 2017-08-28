'use strict';

/* global call_data, func_data */


$(function () {

_.mixin({
toggle: function(a, b) {
    return _.contains(a, b) ? _.without(a,b) : _.union(a,[b]);
},
deepContains: function(arr, x) {
    return _.any(arr, _.partial(_.isEqual, x))
}
});

var $code = $('#code');
hljs.highlightBlock($code[0]);

var node_values = call_data.node_values;
var loop_iterations = call_data.loop_iterations;
var node_loops = func_data.node_loops;
var _current_iteration = {};
$code.find('span[data-type="loop"]').each(function(_, loop_span) {
    _current_iteration[loop_span.dataset.index] = 0;
});

var selected_expressions = [];
var index_to_node = {};

function make_jstree_nodes(prefix, path, val, $node) {
    if (!val) {
        return {
            text: '<span style="color: #b5b5b5">' + _.escape(prefix) + '</span>',
            state: {
                disabled: true,
            },
            icon: false,
            $node: $node,
        }
    }
    var val_repr = _.escape(val[0]).replace(/ /g, '&nbsp;');
    var type_index = val[1];
    var type_name = call_data.type_names[type_index];
    var is_special = type_index < call_data.num_special_types;
    function special(name) {
        return is_special && type_name === name;
    }

    var text = _.escape(prefix) + ' = ';
    if (special('NoneType')) {
        text += '<i>None</i>';
    } else if (type_index == -1) { // exception
        text += '<span style="color: red">' + val_repr + '</span>';
    } else {
        text += '<span style="color: #b5b5b5">' + _.escape(type_name) + ':</span> ' + val_repr;
    }

    var icon;
    if (special('bool')) {
        icon = 'glyphicon glyphicon-' + (val_repr === 'True' ? 'ok' : 'remove');
    } else if (type_index == -1) {
        icon = 'glyphicon glyphicon-warning-sign';
    } else {
        icon = '/static/img/type_icons/';
        if (is_special) {
            if ('str NoneType complex float int list tuple dict set'.indexOf(type_name) > -1) {
                icon += type_name;
            } else {
                icon += {
                    unicode: 'str',
                    bytes: 'str',
                    frozenset: 'set',
                    long: 'int',
                }[type_name];
            }
        } else {
            icon += 'object';
        }
        icon += '.png';
    }

    var result = {
        text: text,
        icon: icon,
        path: path,
        $node: $node,
        state: {
            opened: _.deepContains(open_paths, path),
        }
    };

    var rest = val.slice(_.isObject(val[2]) && !_.isArray(val[2]) ? 3 : 2);
    if (rest.length && !(_(rest).isEqual(['len() = 0']) && is_special)) {
        result.children = rest.map(function(child) {
            if (typeof child === "string") {
                return {
                    icon: false,
                    text: child,
                };
            }
            return make_jstree_nodes(child[0], path.concat([child[0]]), child[1]);
        });
    }
    return result;
}

var open_paths = [];

$('#inspector').jstree({
    core: {
        themes: {
            name: 'proton',
            responsive: true
        }
    },
}).on("hover_node.jstree dehover_node.jstree", function(e, data) {
    var $node = data.node.original.$node;
    if (!$node) {
        return;
    }
    var hovering = e.type === 'hover_node';
    $node.toggleClass('hovering', hovering);
}).on("open_node.jstree", function(e, data) {
    var path = data.node.original.path;
    if (!_(open_paths).deepContains(path)) {
        open_paths.push(path);
    }
}).on("close_node.jstree", function(e, data) {
    var path = data.node.original.path;
    while (_(open_paths).deepContains(path)) {
        var index = _.findIndex(open_paths, _.partial(_.isEqual, path))
        open_paths.splice(index, 1);
    }
});

$code.find('span[data-type="expr"]').each(function() {
    var $this = $(this);
    var tree_index = this.dataset.index;
    $this.toggleClass('expr', tree_index in node_values);
    $this.toggleClass(
        'has-inner',
        (JSON.stringify(node_values[tree_index]) || '').indexOf(',{"inner_call":"') != -1);
    $this.click(function() {
        if ($this.hasClass('hovering')) {
            $this.toggleClass('selected');
            selected_expressions = _.toggle(selected_expressions, tree_index);
        }
        render();
    });
    index_to_node[tree_index] = this;
});

$('#bottom_panel').width($code.width());

function render() {

    $('#inspector, #resize-handle').css({display: selected_expressions.length ? 'block' : 'none'})

    var loop_indices = {};
    function findRanges(iters) {
        if (!iters) {
            return;
        }
        Object.keys(iters).forEach(function(key) {
            var value = iters[key];
            loop_indices[key] = _.pluck(value, 'index');
            findRanges(value[current_iteration(key)].loops);
        });
    }

    function current_iteration(i) {
        if (!(i in loop_indices)) {
            return -1;
        }
        return Math.min(_current_iteration[i], loop_indices[i].length - 1);
    }

    findRanges(loop_iterations);

    function get_value(tree_index) {
        var value = node_values[tree_index];
        var loops = node_loops[tree_index] || [];
        loops.forEach(function(loopIndex) {
            if (value) {
                value = value[current_iteration(loopIndex)];
            }
        });
        return value;
    }

    $code.find('span[data-type="expr"]').each(
        function () {
            var value;
            var $this = $(this);
            if (this.dataset.index in node_values) {
                $this.toggleClass('expr', true);
                value = get_value(this.dataset.index);
            }
            $this.toggleClass('has_value', Boolean(value));
            if (value) {
                $this.on('mouseover mouseout', function (e) {
                    var hovering = e.type === 'mouseover';
                    $this.toggleClass('hovering', hovering);
                    if (hovering) {
                        $('#expr_value').text(value[0]);
                    }
                    e.stopPropagation();
                });
                $this.toggleClass('exception_node', value[1] == -1);
                $this.toggleClass('value_none', value[1] == 0);
                if (value[2] && value[2].inner_call) {
                    $this.append('<a class="inner-call" href="/call/' + value[2].inner_call + '">' +
                                    '<span class="glyphicon glyphicon-share-alt"></span>' +
                                 '</a>')
                } else {
                    $this.children('a.inner-call').remove()
                }
            } else {
                $this.off('mouseover mouseout');
            }
        }
    );

    $code.find('span[data-type="stmt"],span[data-type="loop"]').each(function () {
        var value;
        var $this = $(this);
        if (this.dataset.index in node_values) {
            value = get_value(this.dataset.index);
        }
        $this.toggleClass('stmt_uncovered', !value);
    });

    $('#inspector').jstree(true).settings.core.data = selected_expressions.map(function(tree_index) {
        var node = index_to_node[tree_index];
        var $node = $(node);
        var value = get_value(tree_index);
        return make_jstree_nodes($node.text(), [tree_index], value, $node);
    });
    $('#inspector').jstree(true).refresh();

    $('.loop-navigator').remove();

    $code.find('span[data-type="loop"]').each(function(_, loop_span) {

        var loopIndex = loop_span.dataset.index;

        var buttonGroup = $('<div>', {
            class: "btn-group loop-navigator",
            role: "group",
        }).css({
            position: 'absolute',
            top: $(loop_span).offset().top - $code.offset().top,
            right: ($code[0].offsetWidth + 5) + 'px',
        });

        function mkButton(cls, disabled, html, onclick) {
            var attrs = {
                type: 'button',
                class: 'btn btn-default btn-xs ' + cls,
                html: html,
            }
            if (disabled) {
                attrs.disabled = 'disabled';
            }
            if (cls === 'dropdown-toggle') {
                attrs['data-toggle'] = 'dropdown';
            }
            var button = $('<button>', attrs);
            if (onclick) {
                button.click(onclick);
            }
            return button;
        }

        var current = current_iteration(loopIndex);

        function changeNumber(num) {
            return function() {
                _current_iteration[loopIndex] = num;
                render();
            }
        }

        if (current >= 0) {
            var disabled = current === 0;
            buttonGroup.append(mkButton(
                '',
                disabled,
                '&lt;',
                changeNumber(current - 1)
            ));

            var innerGroup = $('<div class="btn-group dropdown" role="group">');
            buttonGroup.append(innerGroup);
            innerGroup.append(
                mkButton(
                    'dropdown-toggle',
                    false,
                    loop_indices[loopIndex][current],
                    null
                ))
            var dropdownList = $('<ul class="dropdown-menu">');
            loop_indices[loopIndex].forEach(function(iterationIndex, rawIndex) {
                dropdownList.append(
                    $('<li><a>' + iterationIndex + '</a></li>')
                    .click(changeNumber(rawIndex))
                );
            });
            innerGroup.append(dropdownList);

            disabled = current === loop_indices[loopIndex].length - 1;
            buttonGroup.append(mkButton(
                '',
                disabled,
                '&gt;',
                changeNumber(current + 1)
            ))

            $code.append(buttonGroup);
        }

    });
}

render();

(function() {

// Based on https://stackoverflow.com/a/8960307/2482744

var p = $('#inspector')[0];
var resizer = $('#resize-handle')[0];
resizer.addEventListener('mousedown', initDrag, false);

var startY, startHeight;

function initDrag(e) {
   startY = e.clientY;
   startHeight = parseInt(document.defaultView.getComputedStyle(p).height, 10);
   document.documentElement.addEventListener('mousemove', doDrag, false);
   document.documentElement.addEventListener('mouseup', stopDrag, false);
}

function doDrag(e) {
   p.style.height = (startHeight - Math.max(10, e.clientY) + startY) + 'px';
}

function stopDrag() {
    document.documentElement.removeEventListener('mousemove', doDrag, false);
    document.documentElement.removeEventListener('mouseup', stopDrag, false);
}

})()

});
