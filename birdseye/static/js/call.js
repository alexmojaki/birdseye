'use strict';

document.addEventListener( 'DOMContentLoaded', async function () {
    _.mixin({
        toggle: function (a, b) {
            return _.contains(a, b) ? _.without(a, b) : _.union(a, [b]);
        },
        deepContains: function (arr, x) {
            return _.any(arr, _.partial(_.isEqual, x))
        }
    });

    const static_url = "";

    localforage.config({name: "birdseye", storeName: "birdseye"});
    const call_id = new URLSearchParams(window.location.search).get('call_id');
    const call = await localforage.getItem("calls/" + call_id);
    const call_data = call.data;
    const call_success = call.success;
    const func = await localforage.getItem("functions/" + call.function_id);
    const func_data = func.data;

    var $code = $('#code');
    $code[0].innerHTML = func.html_body;
    hljs.highlightBlock($code[0]);

    var node_values = call_data.node_values;
    var loop_iterations = call_data.loop_iterations;
    var node_loops = func_data.node_loops;

    if (_.isEmpty(node_loops)) {
        $('#arrows-holder').hide();
    }

    var _current_iteration = {};
    $code.find('.loop').each(function (_, loop_span) {
        _current_iteration[loop_span.dataset.index] = 0;
    });

    if (!call_success) {
        // Go to the end of all loops to see what
        // happened when there was an exception
        var fill_last_iterations = function (loops) {
            if (!loops) {
                return;
            }
            Object.keys(loops).forEach(function (tree_index) {
                var loop = loops[tree_index];
                var iteration = _.last(loop);
                _current_iteration[tree_index] = iteration.index;
                fill_last_iterations(iteration.loops);
            });
        };
        fill_last_iterations(loop_iterations);
    }

    var normal_stmt_value = 'fine';

    var selected_boxes = [];
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
        var val_repr = '<div class="inspector-value">' + _.escape(val[0]) + '</div>';
        var type_index = val[1];
        var type_name = call_data.type_names[type_index];
        var is_special = type_index < call_data.num_special_types;

        function special(name) {
            return is_special && type_name === name;
        }

        var text = _.escape(prefix) + (type_index < 0 ? ' : ' : ' = ');
        if (type_index === -2) {
            text += '<i>' + normal_stmt_value + '</i>';
        } else {
            if (special('NoneType')) {
                text += '<i>None</i>';
            } else if (type_index === -1) { // exception
                text += '<span style="color: red">' + val_repr + '</span>';
            } else if (val[2].dataframe && val[3] && (val[3][1].length > 4)) {
                var table = dataframeTable(val);
                text += table[0].outerHTML
            } else {
                text += '<span style="color: #b5b5b5">' + _.escape(type_name) + ':</span> ' + val_repr;
            }
        }

        var icon;
        if (special('bool')) {
            icon = 'glyphicon glyphicon-' + (val[0] === 'True' ? 'ok' : 'remove');
        } else if (type_index === -1) {
            icon = 'glyphicon glyphicon-warning-sign';
        } else if (type_index === -2) {
            icon = 'glyphicon glyphicon-ok';
        } else {
            icon = static_url + 'img/type_icons/';
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

        var children = [];
        var len = val[2].len;
        if (len !== undefined && !(len === 0 && is_special)) {
            children.push({
                icon: false,
                text: 'len() = ' + len,
            });
        }

        $.merge(children, val.slice(3).map(function (child) {
            return make_jstree_nodes(child[0], path.concat([child[0]]), child[1]);
        }));

        if (children.length) {
            result.children = children;
        }

        return result;
    }

    function dataframeTable(val) {
        var meta = val[2].dataframe;
        var numCols = val.length - 3;
        var numRows = val[3][1].length - 4;
        var i, j, value, column;
        var table = $('<table>').addClass('dataframe table table-striped table-hover');
        var header = $('<tr>');
        header.append($('<th>'));
        table.append(header);
        var rows = [];
        for (i = 0; i < numRows; i++) {
            var row;
            if (i === meta.row_break) {
                row = $('<tr>');
                for (j = 0; j < numCols + 1 + (meta.col_break ? 1 : 0); j++) {
                    row.append($('<td>')
                        .text('...')
                        .css({'text-align': 'center'}));
                }
                table.append(row);
            }
            row = $('<tr>');
            table.append(row);
            rows.push(row);
            column = val[3];
            var label = column[1][4 + i][0];
            row.append($('<th>').text(label));
        }
        for (i = 0; i < numCols; i++) {
            if (i === meta.col_break) {
                header.append($('<th>').text('...'));
            }
            column = val[3 + i];
            header.append($('<th>').text(column[0]));
            var values = [];
            var isNumeric = true;
            var maxDecimals = 1;
            for (j = 0; j < numRows; j++) {
                value = column[1][4 + j][1][0];
                values.push(value);
                isNumeric &= !isNaN(parseFloat(value)) || value.toLowerCase() === 'nan';
                var decimals = value.split(".")[1];
                if (decimals) {
                    maxDecimals = Math.max(maxDecimals, decimals.length);
                }
            }
            for (j = 0; j < numRows; j++) {
                if (i === meta.col_break) {
                    rows[j].append($('<td>').text('...'));
                }
                value = values[j];
                if (isNumeric) {
                    value = parseFloat(value).toFixed(Math.min(maxDecimals, 6));
                }
                rows[j].append($('<td>').text(value).toggleClass('numeric', isNumeric));
            }
        }
        return table;
    }

    var open_paths = [];

    $('#inspector').jstree({
        core: {
            themes: {
                name: 'proton',
                responsive: true
            }
        },
    }).on("hover_node.jstree dehover_node.jstree", function (e, data) {
        var $node = data.node.original.$node;
        if (!$node) {
            return;
        }
        var hovering = e.type === 'hover_node';
        $node.toggleClass('hovering', hovering);
    }).on("open_node.jstree", function (e, data) {
        var path = data.node.original.path;
        if (!_(open_paths).deepContains(path)) {
            open_paths.push(path);
        }
    }).on("close_node.jstree", function (e, data) {
        var path = data.node.original.path;
        while (_(open_paths).deepContains(path)) {
            var index = _.findIndex(open_paths, _.partial(_.isEqual, path));
            open_paths.splice(index, 1);
        }
    });

    $code.find('span[data-index]').each(function () {
        var $this = $(this);
        var tree_index = this.dataset.index;
        var json = JSON.stringify(node_values[tree_index]) || '';
        $this.toggleClass('box', tree_index in node_values && !(
            // This is a statement/comprehension node that never encounters an exception,
            // or has any metadata, so it never has a 'value' worth checking.
            ($this.hasClass('stmt') || $this.hasClass('loop')) &&
            -1 === json.indexOf('-1') &&
            -1 === json.indexOf('inner_call')));
        $this.toggleClass(
            'has-inner',
            json.indexOf('"inner_calls":["') !== -1);
        $this.click(function () {
            if ($this.hasClass('hovering')) {
                $this.toggleClass('selected');
                selected_boxes = _.toggle(selected_boxes, tree_index);
            }
            render();
        });
        index_to_node[tree_index] = this;
    });

    function render() {

        $('#inspector, #resize-handle').css({display: selected_boxes.length ? 'block' : 'none'});

        var loop_indices = {};

        function findRanges(iters) {
            if (!iters) {
                return;
            }
            Object.keys(iters).forEach(function (key) {
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
            loops.forEach(function (loopIndex) {
                if (value) {
                    value = value[current_iteration(loopIndex)];
                }
            });
            return value;
        }

        $code.find('span[data-index]').each(
            function () {
                var value;
                var $this = $(this);
                var tree_index = this.dataset.index;
                if (tree_index in node_values) {
                    value = get_value(tree_index);
                }
                $this.toggleClass('has_value', Boolean(value));
                $this.toggleClass('stmt_uncovered', $this.hasClass('stmt') && !value);

                if (value && $this.hasClass('box')) {
                    $this.on('mouseover mouseout', function (e) {
                        var hovering = e.type === 'mouseover';
                        $this.toggleClass('hovering', hovering);
                        if (hovering) {
                            if (value[1] === -2) {
                                value[0] = normal_stmt_value;
                            }
                            $('#box_value').text(value[0]);
                        }
                        e.stopPropagation();
                    });
                    $this.toggleClass('exception_node', value[1] === -1);
                    $this.toggleClass('value_none', value[1] === 0 || value[1] === -2);
                    $this.children('a.inner-call').remove();

                    var inner_calls = value[2].inner_calls || [];
                    var place_link = function (inner_call, css) {
                        var link = $('<a class="inner-call" href="?call_id=' + inner_call + '">' +
                            '<span class="glyphicon glyphicon-share-alt"></span>' +
                            '</a>')
                            .css(css);
                        $this.append(link);
                    };
                    if (inner_calls.length === 1) {
                        place_link(inner_calls[0], {bottom: '-4px'});
                    } else if (inner_calls.length >= 2) {
                        place_link(inner_calls[0], {top: 0});
                        place_link(inner_calls[inner_calls.length - 1], {bottom: '-4px'});
                    }
                } else {
                    $this.off('mouseover mouseout');
                }
            }
        );

        var inspector = $('#inspector');
        inspector.jstree(true).settings.core.data = selected_boxes.map(function (tree_index) {
            var node = index_to_node[tree_index];
            var $node = $(node);
            var value = get_value(tree_index);
            return make_jstree_nodes($node.text(), [tree_index], value, $node);
        });
        inspector.jstree(true).refresh();

        $('.loop-navigator').remove();

        $code.find('.loop').each(function (_, loop_span) {

            var loopIndex = loop_span.dataset.index;

            var buttonGroup = $('<div>', {
                class: "btn-group loop-navigator",
                role: "group",
            }).css({
                position: 'absolute',
                top: $(loop_span).offset().top - $code.offset().top,
                right: '5px',
            });

            function mkButton(cls, disabled, html, onclick) {
                var attrs = {
                    type: 'button',
                    class: 'btn btn-default btn-xs ' + cls,
                    html: html,
                };
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
                return function () {
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
                    ));
                var dropdownList = $('<ul class="dropdown-menu">');
                loop_indices[loopIndex].forEach(function (iterationIndex, rawIndex) {
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
                ));

                $('#arrows-holder').append(buttonGroup);
            }

        });
    }

    render();

    // This fixes a weird bug where the bottom panel disappears if the page
    // is scrolled to the bottom at page load
    setTimeout(function () {
        scrollBy(0, -1)
    }, 100);

    (function () {

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
