import unittest
from time import sleep

from littleutils import only
from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

from birdseye import eye, BirdsEye


@eye
def foo():
    for i in range(20):
        for j in range(3):
            int(i * 13 + j * 17)
            if i > 0:
                try:
                    assert j
                except AssertionError:
                    pass
    str(bar())

    x = list(range(1, 30, 2))
    list(x)


@eye
def bar():
    pass


full_eye = BirdsEye(capture_options=dict(arguments='full', result='full', expressions='full'))


@full_eye
def full_capture(items):
    return {'total': len(items)}


class TestInterface(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.set_window_size(1600, 1200)
        self.driver.implicitly_wait(2)

    def tearDown(self):
        self.driver.quit()

    def test(self):
        try:
            self._do_test()
        except:
            self.driver.save_screenshot('error_screenshot.png')
            raise

    def _do_test(self):
        foo()
        driver = self.driver

        # On the index page, note the links to the function and call
        driver.get('http://localhost:7777/')
        function_link = driver.find_element(By.LINK_TEXT, 'foo')
        function_url = function_link.get_attribute('href')
        call_url = function_link.find_element(By.XPATH, '..//i/..').get_attribute('href')

        # On the file page, check that the links still match
        driver.find_element(By.PARTIAL_LINK_TEXT, 'test_interface').click()
        function_link = driver.find_element(By.LINK_TEXT, 'foo')
        self.assertEqual(function_link.get_attribute('href'), function_url)
        self.assertEqual(call_url, function_link.find_element(By.XPATH, '..//i/..').get_attribute('href'))

        # Finally navigate to the call and check the original call_url
        function_link.click()
        driver.find_element(By.CSS_SELECTOR, 'table a').click()
        self.assertEqual(driver.current_url, call_url)

        # Test hovering, clicking on expressions, and stepping through loops

        vals = {'i': 0, 'j': 0}
        exprs = driver.find_elements(By.CLASS_NAME, 'has_value')
        expr_value = driver.find_element(By.ID, 'box_value')

        expr_strings = [
            'i * 13 + j * 17',
            'j * 17',
            'i * 13',
        ]

        def find_by_text(text, elements):
            return only(n for n in elements if n.text == text)

        def find_expr(text):
            return find_by_text(text, exprs)

        def tree_nodes(root=driver):
            return root.find_elements(By.CLASS_NAME, 'jstree-node')

        def select(node, prefix, value_text):
            self.assertIn('box', classes(node))
            self.assertIn('has_value', classes(node))
            self.assertNotIn('selected', classes(node))
            node.click()
            self.assertIn('selected', classes(node))
            self.assertEqual(expr_value.text, value_text)
            tree_node = tree_nodes()[-1]
            self.assertEqual(tree_node.text, prefix + value_text)
            return tree_node

        def classes(node):
            return set(node.get_attribute('class').split())

        def assert_classes(node, *cls):
            self.assertEqual(classes(node), set(cls))

        for i, expr in enumerate(expr_strings):
            find_expr(expr).click()

        def step(loop, increment):
            selector = '.loop-navigator > .btn:%s-child' % ('first' if increment == -1 else 'last')
            buttons = driver.find_elements(By.CSS_SELECTOR, selector)
            self.assertEqual(len(buttons), 2)
            buttons[loop].click()
            vals['ij'[loop]] += increment

            for expr in expr_strings:
                ActionChains(driver).move_to_element(find_expr(expr)).perform()
                value = str(eval(expr, {}, vals))
                self.assertEqual(expr_value.text, value)
                node = only(n for n in tree_nodes()
                            if n.text.startswith(expr + ' ='))
                self.assertEqual(node.text, '%s = int: %s' % (expr, value))

        stmt = find_by_text('assert j', driver.find_elements(By.CLASS_NAME, 'stmt'))
        assert_classes(stmt, 'stmt', 'stmt_uncovered', 'box')

        step(0, 1)
        select(stmt, 'assert j : ', 'AssertionError')
        assert_classes(stmt, 'stmt', 'selected', 'box', 'hovering', 'has_value', 'exception_node')
        step(1, 1)
        self.assertEqual(tree_nodes()[-1].text, 'assert j : fine')
        assert_classes(stmt, 'stmt', 'selected', 'box', 'has_value', 'value_none')
        step(1, 1)
        step(0, -1)
        self.assertTrue({'stmt', 'stmt_uncovered', 'selected', 'box'} <= classes(stmt))
        step(1, -1)

        # Expanding values
        x_node = find_expr('x')
        tree_node = select(x_node, 'x = list: ', '[1, 3, 5, ..., 25, 27, 29]')
        tree_node.find_element(By.CLASS_NAME, 'jstree-ocl').click()  # expand
        sleep(0.2)
        self.assertEqual([n.text for n in tree_nodes(tree_node)],
                         ['len() = 15',
                          '0 = int: 1',
                          '1 = int: 3',
                          '2 = int: 5',
                          '3 = int: 7',
                          '4 = int: 9',
                          '10 = int: 21',
                          '11 = int: 23',
                          '12 = int: 25',
                          '13 = int: 27',
                          '14 = int: 29']),

        # Click on an inner call
        find_expr('bar()').find_element(By.CLASS_NAME, 'inner-call').click()
        self.assertEqual(driver.find_element(By.TAG_NAME, 'h2').text,
                         'Call to function: bar')

    def test_full_capture(self):
        try:
            self._do_test_full_capture()
        except:
            self.driver.save_screenshot('error_screenshot.png')
            raise

    def _do_test_full_capture(self):
        full_capture(list(range(20)))
        driver = self.driver
        driver.get('http://localhost:7777/call/' + full_eye._last_call_id)

        # Complete copies of the argument and result replace the short summaries
        self.assertFalse(driver.find_element(By.CLASS_NAME, 'args-table').is_displayed())
        self.assertFalse(driver.find_element(By.ID, 'result-summary').is_displayed())

        # Small values are labelled with their complete repr
        complete = 'items = list: %r' % list(range(20))
        argument = driver.find_element(By.CSS_SELECTOR, '#argument-snapshots .jstree-node')
        self.assertEqual(argument.text, complete)
        argument.find_element(By.CLASS_NAME, 'jstree-ocl').click()  # expand
        sleep(0.2)
        self.assertEqual([n.text for n in argument.find_elements(By.CLASS_NAME, 'jstree-node')],
                         ['len() = 20'] + ['%s = int: %s' % (i, i) for i in range(20)])

        result = driver.find_element(By.CSS_SELECTOR, '#result-snapshot .jstree-node')
        self.assertEqual(result.text, "result = dict: {'total': 20}")

        # Values inside the function are complete too, in the inspector at the bottom
        only(n for n in driver.find_elements(By.CLASS_NAME, 'has_value') if n.text == 'items').click()
        tree_node = driver.find_elements(By.CSS_SELECTOR, '#inspector .jstree-node')[-1]
        self.assertEqual(tree_node.text, complete)
        tree_node.find_element(By.CLASS_NAME, 'jstree-ocl').click()  # expand
        sleep(0.2)
        self.assertEqual([n.text for n in tree_node.find_elements(By.CLASS_NAME, 'jstree-node')],
                         ['len() = 20'] + ['%s = int: %s' % (i, i) for i in range(20)])
